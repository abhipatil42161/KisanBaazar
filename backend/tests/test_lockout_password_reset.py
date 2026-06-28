"""Phase C iteration 10: Brute-force lockout + password reset flow.

Covers:
- 5 wrong logins -> 429; "(2 remaining)" on attempt 3, "(1 remaining)" on attempt 4
- During lockout, correct password also rejected with 429
- 429 carries Retry-After header
- Successful login clears the failed-attempt counter
- Identifier is {ip}:{email}: locking one email doesn't lock another
- /auth/forgot-password: existing email -> token in DB + log line; non-existent -> no token but same 200
- /auth/forgot-password is CSRF-exempt (no cookies/no CSRF header works)
- /auth/reset-password: valid token -> 200 + password change + token marked used
- After reset, old password fails; new password works
- Token reuse -> 400; bogus token -> 400; expired token -> 400; short pw -> 400
- Reset clears active lockouts for the email
- Mongo indexes: TTL on expires_at, unique on token, unique on identifier
- CSRF regression: /api/products CSRF behaviour preserved
"""
import os
import re
import time
import uuid
import pytest
import requests
import subprocess

from motor.motor_asyncio import AsyncIOMotorClient
import asyncio
from datetime import datetime, timedelta, timezone

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"
# Local backend socket — used for lockout tests so the source IP is stable.
# (Public URL goes through Cloudflare which may rotate X-Forwarded-For across pops,
#  defeating the per-{ip}:{email} brute-force counter.)
LOCAL_API = "http://localhost:8001/api"
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")

BACKEND_LOG = "/var/log/supervisor/backend.err.log"


# ------------------ Mongo helpers (sync via subprocess to keep tests simple) ------------------
def _mongo_run(js: str) -> str:
    r = subprocess.run(
        ["mongosh", DB_NAME, "--quiet", "--eval", js],
        capture_output=True, text=True, timeout=20,
    )
    return (r.stdout or "") + (r.stderr or "")


def _clear_login_attempts_for(email: str):
    _mongo_run(f'db.login_attempts.deleteMany({{identifier:{{$regex:":{email}$"}}}})')


def _delete_reset_tokens_for(email: str):
    _mongo_run(f'db.password_reset_tokens.deleteMany({{email:"{email}"}})')


def _delete_user(email: str):
    _mongo_run(f'db.users.deleteOne({{email:"{email}"}})')


def _set_token_expired(token: str):
    past = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    _mongo_run(f'db.password_reset_tokens.updateOne({{token:"{token}"}},{{$set:{{expires_at:new Date("{past}")}}}})')


def _read_latest_reset_link(email: str) -> str:
    """Tail the backend log and parse the latest PASSWORD_RESET_LINK token for `email`.
    Backend lowercases the email before logging, so we match case-insensitively.
    """
    try:
        with open(BACKEND_LOG, "r") as f:
            lines = f.readlines()
    except FileNotFoundError:
        return ""
    pat = re.compile(rf"PASSWORD_RESET_LINK email={re.escape(email.lower())} link=\S*token=([A-Za-z0-9_\-]+)")
    for line in reversed(lines[-2000:]):
        m = pat.search(line)
        if m:
            return m.group(1)
    return ""


def _register_temp(email: str, password: str = "Initial123") -> dict:
    s = requests.Session()
    r = s.post(f"{API}/auth/register", json={
        "email": email, "password": password, "name": "Temp Test", "role": "buyer",
    }, timeout=20)
    assert r.status_code == 200, f"register {email}: {r.status_code} {r.text}"
    return s


# ============================================================
# 1) Brute-force lockout
# ============================================================
class TestBruteForceLockout:
    def setup_method(self, method):
        # ensure a clean lockout state for the canonical victim
        self.victim = f"TEST_lock_{uuid.uuid4().hex[:8]}@example.com"
        self.pw = "GoodPass123"
        _register_temp(self.victim, self.pw)
        _clear_login_attempts_for(self.victim)

    def teardown_method(self, method):
        _clear_login_attempts_for(self.victim)
        _delete_user(self.victim)

    def _bad_login(self):
        return requests.post(f"{LOCAL_API}/auth/login",
                             json={"email": self.victim, "password": "WRONG"},
                             timeout=15)

    def test_lockout_progression_and_429(self):
        # Attempts 1,2: generic 401 "Invalid credentials"
        for i in range(1, 3):
            r = self._bad_login()
            assert r.status_code == 401, f"attempt {i}: {r.status_code} {r.text}"
            assert "remaining" not in r.json().get("detail", "").lower()

        # Attempt 3: should show "(2 attempts remaining)"
        r3 = self._bad_login()
        assert r3.status_code == 401, r3.text
        assert "2 attempts remaining" in r3.json().get("detail", ""), r3.text

        # Attempt 4: should show "(1 attempt remaining)"
        r4 = self._bad_login()
        assert r4.status_code == 401, r4.text
        assert "1 attempt remaining" in r4.json().get("detail", ""), r4.text

        # Attempt 5: triggers lockout -> 429 (no Retry-After on triggering response;
        # backend sets Retry-After on subsequent locked-out attempts via check_lockout)
        r5 = self._bad_login()
        assert r5.status_code == 429, f"expected 429 on attempt 5, got {r5.status_code} {r5.text}"

        # Attempt 6: still 429 AND now carries Retry-After
        r6 = self._bad_login()
        assert r6.status_code == 429
        assert r6.headers.get("retry-after"), f"Retry-After header missing on 6th attempt: {dict(r6.headers)}"

    def test_correct_password_rejected_during_lockout(self):
        for _ in range(5):
            self._bad_login()
        # Now try CORRECT password — should still be 429
        r = requests.post(f"{LOCAL_API}/auth/login",
                          json={"email": self.victim, "password": self.pw}, timeout=15)
        assert r.status_code == 429, f"correct pw during lock should 429, got {r.status_code} {r.text}"

    def test_successful_login_clears_counter(self):
        # 3 bad attempts, then a correct one
        for _ in range(3):
            self._bad_login()
        good = requests.post(f"{LOCAL_API}/auth/login",
                             json={"email": self.victim, "password": self.pw}, timeout=15)
        assert good.status_code == 200, good.text
        # login_attempts record should be gone
        out = _mongo_run(f'db.login_attempts.find({{identifier:{{$regex:":{self.victim}$"}}}}).toArray()')
        assert "[]" in out.replace(" ", "").replace("\n", "") or self.victim not in out, \
            f"expected no login_attempts after success, got: {out}"

    def test_per_email_isolation(self):
        # Lock the primary victim
        for _ in range(5):
            self._bad_login()
        r_lock = self._bad_login()
        assert r_lock.status_code == 429

        # A different fresh user must still be able to log in
        other = f"TEST_lock_other_{uuid.uuid4().hex[:8]}@example.com"
        try:
            _register_temp(other, "GoodPass123")
            _clear_login_attempts_for(other)
            r = requests.post(f"{LOCAL_API}/auth/login",
                              json={"email": other, "password": "GoodPass123"}, timeout=15)
            assert r.status_code == 200, f"other user should login fine: {r.status_code} {r.text}"
        finally:
            _clear_login_attempts_for(other)
            _delete_user(other)


# ============================================================
# 2) Forgot password
# ============================================================
class TestForgotPassword:
    def test_existing_email_logs_link_and_creates_token(self):
        email = f"TEST_fp_exist_{uuid.uuid4().hex[:8]}@example.com"
        _register_temp(email)
        try:
            r = requests.post(f"{API}/auth/forgot-password", json={"email": email}, timeout=15)
            assert r.status_code == 200, r.text
            msg = r.json().get("message", "")
            assert "reset link" in msg.lower() or "if an account exists" in msg.lower()

            # Give the logger a moment to flush
            time.sleep(0.5)
            tok = _read_latest_reset_link(email)
            assert tok and len(tok) > 10, f"reset link not found in {BACKEND_LOG} for {email}"

            # Token must exist in DB, with used=false and future expiry
            out = _mongo_run(f'JSON.stringify(db.password_reset_tokens.findOne({{token:"{tok}"}}))')
            assert email.lower() in out.lower(), f"token row missing or wrong email: {out}"
            assert '"used":false' in out.replace(" ", ""), f"expected used=false: {out}"
        finally:
            _delete_reset_tokens_for(email)
            _delete_user(email)

    def test_nonexistent_email_no_enumeration(self):
        ghost = f"TEST_ghost_{uuid.uuid4().hex[:8]}@example.com"
        r = requests.post(f"{API}/auth/forgot-password", json={"email": ghost}, timeout=15)
        assert r.status_code == 200
        msg = r.json().get("message", "")
        assert "if an account exists" in msg.lower() or "reset link" in msg.lower()

        # No token row created
        out = _mongo_run(f'db.password_reset_tokens.countDocuments({{email:"{ghost}"}})')
        assert "0" in out, f"unexpected token row for ghost email: {out}"

    def test_csrf_exempt_no_cookies(self):
        # Bare requests.post with no cookies, no CSRF header -> still 200
        email = f"TEST_fp_csrf_{uuid.uuid4().hex[:8]}@example.com"
        _register_temp(email)
        try:
            r = requests.post(f"{API}/auth/forgot-password",
                              json={"email": email},
                              headers={"Content-Type": "application/json"},
                              timeout=15)
            assert r.status_code == 200, r.text
        finally:
            _delete_reset_tokens_for(email)
            _delete_user(email)


# ============================================================
# 3) Reset password
# ============================================================
class TestResetPassword:
    def _make_token(self, email):
        requests.post(f"{API}/auth/forgot-password", json={"email": email}, timeout=15)
        time.sleep(0.5)
        return _read_latest_reset_link(email)

    def test_full_reset_round_trip(self):
        email = f"TEST_rp_{uuid.uuid4().hex[:8]}@example.com"
        old_pw, new_pw = "Initial123", "NewSecret456"
        _register_temp(email, old_pw)
        try:
            tok = self._make_token(email)
            assert tok, "no token in logs"

            r = requests.post(f"{API}/auth/reset-password",
                              json={"token": tok, "new_password": new_pw}, timeout=15)
            assert r.status_code == 200, r.text

            # Old password fails
            r_old = requests.post(f"{API}/auth/login",
                                  json={"email": email, "password": old_pw}, timeout=15)
            assert r_old.status_code == 401, f"old pw should fail: {r_old.status_code}"

            # New password works
            r_new = requests.post(f"{API}/auth/login",
                                  json={"email": email, "password": new_pw}, timeout=15)
            assert r_new.status_code == 200, f"new pw should succeed: {r_new.status_code} {r_new.text}"

            # Token marked used
            out = _mongo_run(f'JSON.stringify(db.password_reset_tokens.findOne({{token:"{tok}"}}))')
            assert '"used":true' in out.replace(" ", ""), f"token not marked used: {out}"

            # Reuse should fail
            r_reuse = requests.post(f"{API}/auth/reset-password",
                                    json={"token": tok, "new_password": "AnotherPw789"}, timeout=15)
            assert r_reuse.status_code == 400
            assert "invalid" in r_reuse.json().get("detail", "").lower()
        finally:
            _delete_reset_tokens_for(email)
            _clear_login_attempts_for(email)
            _delete_user(email)

    def test_bogus_token_400(self):
        r = requests.post(f"{API}/auth/reset-password",
                          json={"token": "this-is-not-a-real-token-xyz", "new_password": "abcdef"}, timeout=15)
        assert r.status_code == 400
        assert "invalid" in r.json().get("detail", "").lower()

    def test_short_password_400(self):
        # Even without a real token, length check should run first
        email = f"TEST_rp_short_{uuid.uuid4().hex[:8]}@example.com"
        _register_temp(email)
        try:
            tok = self._make_token(email)
            assert tok
            r = requests.post(f"{API}/auth/reset-password",
                              json={"token": tok, "new_password": "ab"}, timeout=15)
            assert r.status_code == 400
            assert "at least" in r.json().get("detail", "").lower() or "6" in r.json().get("detail", "")
        finally:
            _delete_reset_tokens_for(email)
            _delete_user(email)

    def test_expired_token_400(self):
        email = f"TEST_rp_exp_{uuid.uuid4().hex[:8]}@example.com"
        _register_temp(email)
        try:
            tok = self._make_token(email)
            assert tok
            _set_token_expired(tok)
            r = requests.post(f"{API}/auth/reset-password",
                              json={"token": tok, "new_password": "Initial123New"}, timeout=15)
            assert r.status_code == 400
            assert "invalid" in r.json().get("detail", "").lower() or "expired" in r.json().get("detail", "").lower()
        finally:
            _delete_reset_tokens_for(email)
            _delete_user(email)

    def test_reset_clears_lockout(self):
        email = f"TEST_rp_unlock_{uuid.uuid4().hex[:8]}@example.com"
        old_pw, new_pw = "Initial123", "FreshPw456"
        _register_temp(email, old_pw)
        try:
            # Lock the account (use LOCAL_API for stable IP-based identifier)
            for _ in range(5):
                requests.post(f"{LOCAL_API}/auth/login",
                              json={"email": email, "password": "WRONG"}, timeout=15)
            # Confirm locked
            r_lock = requests.post(f"{LOCAL_API}/auth/login",
                                   json={"email": email, "password": old_pw}, timeout=15)
            assert r_lock.status_code == 429, f"expected lock 429, got {r_lock.status_code}"

            # Reset password
            tok = self._make_token(email)
            assert tok
            rr = requests.post(f"{API}/auth/reset-password",
                               json={"token": tok, "new_password": new_pw}, timeout=15)
            assert rr.status_code == 200

            # Login with new password should now succeed (lockout cleared)
            ok = requests.post(f"{LOCAL_API}/auth/login",
                               json={"email": email, "password": new_pw}, timeout=15)
            assert ok.status_code == 200, f"login after reset should succeed, got {ok.status_code} {ok.text}"
        finally:
            _delete_reset_tokens_for(email)
            _clear_login_attempts_for(email)
            _delete_user(email)


# ============================================================
# 4) MongoDB indexes
# ============================================================
class TestMongoIndexes:
    def test_password_reset_tokens_indexes(self):
        out = _mongo_run('JSON.stringify(db.password_reset_tokens.getIndexes())')
        flat = out.replace(" ", "")
        assert '"expires_at":1' in flat, f"missing expires_at index: {out}"
        assert '"expireAfterSeconds":0' in flat, f"expires_at must be TTL with expireAfterSeconds:0: {out}"
        # token unique
        assert '"token":1' in flat, f"missing token index: {out}"
        assert '"unique":true' in flat, f"expected at least one unique index: {out}"

    def test_login_attempts_identifier_unique(self):
        out = _mongo_run('JSON.stringify(db.login_attempts.getIndexes())')
        flat = out.replace(" ", "")
        assert '"identifier":1' in flat, f"missing identifier index: {out}"
        assert '"unique":true' in flat, f"identifier must be unique: {out}"


# ============================================================
# 5) Cookie+CSRF regression (smoke)
# ============================================================
class TestCsrfRegression:
    def test_login_still_sets_kb_and_csrf(self, test_creds):
        email, pw = test_creds["farmer"]
        s = requests.Session()
        r = s.post(f"{API}/auth/login",
                   json={"email": email, "password": pw}, timeout=15)
        assert r.status_code == 200, r.text
        assert s.cookies.get("kb_token")
        assert s.cookies.get("csrf_token")
        body = r.json()
        assert "token" not in body
        assert "csrf_token" in body

    def test_post_products_without_csrf_403_with_csrf_2xx(self, test_creds):
        email, pw = test_creds["farmer"]
        s = requests.Session()
        r = s.post(f"{API}/auth/login",
                   json={"email": email, "password": pw}, timeout=15)
        assert r.status_code == 200
        sample = {
            "title": f"TEST_lockout_csrf_{uuid.uuid4().hex[:6]}",
            "description": "csrf regression",
            "category": "vegetables", "price": 10.0, "unit": "kg", "moq": 1, "available_qty": 5,
            "quality_grade": "A", "organic": False, "export_ready": False, "images": [],
            "location": "Nashik", "state": "Maharashtra", "auction": False,
        }
        # without CSRF -> 403
        r_no = s.post(f"{API}/products", json=sample,
                      headers={"Content-Type": "application/json"}, timeout=15)
        assert r_no.status_code == 403
        # with CSRF -> 2xx
        r_ok = s.post(f"{API}/products", json=sample,
                      headers={"Content-Type": "application/json",
                               "X-CSRF-Token": s.cookies.get("csrf_token")}, timeout=15)
        assert r_ok.status_code in (200, 201), r_ok.text
        pid = r_ok.json()["product_id"]
        # cleanup
        s.delete(f"{API}/products/{pid}",
                 headers={"X-CSRF-Token": s.cookies.get("csrf_token")}, timeout=15)
        # unauthenticated -> 401
        r_un = requests.post(f"{API}/products", json=sample,
                             headers={"Content-Type": "application/json"}, timeout=15)
        assert r_un.status_code == 401
