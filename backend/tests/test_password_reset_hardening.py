"""Tests for the password-reset system hardening.

Covers:
- Unit: verify_pw() never raises on legacy/corrupt/missing hashes
        (previously crashed with `ValueError: Invalid salt`)
- Unit: is_valid_bcrypt_hash() correctly classifies hashes
- Unit: _reject_if_password_reused() skips corrupt history entries safely,
        and still correctly rejects a genuinely reused password
- Unit: _history_entry() never returns an invalid/empty entry to $push
- Integration: OTP-based password reset, full round trip (real OTP code
  obtained by calling otp_service directly — no email inbox needed)
- Integration: OTP already-consumed retry is treated as success (idempotent)
- Integration: Email-link reset — reused-password rejection end-to-end
"""
import asyncio
import os
import sys
import uuid
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import server as srv  # noqa: E402
import otp_service  # noqa: E402

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"


def _register_temp(email: str, password: str = "Initial123!") -> None:
    r = requests.post(f"{API}/auth/register", json={
        "email": email, "password": password, "name": "Temp Test", "role": "buyer",
    }, timeout=20)
    assert r.status_code == 200, f"register {email}: {r.status_code} {r.text}"


def _delete_user(email: str):
    asyncio.get_event_loop().run_until_complete(srv.db.users.delete_many({"email": email}))


# ============================================================
# 1) Unit tests — bcrypt hardening (the actual reported bug)
# ============================================================
class TestVerifyPwHardening:
    def test_valid_hash_matches_correct_password(self):
        h = srv.hash_pw("CorrectHorse123!")
        assert srv.verify_pw("CorrectHorse123!", h) is True

    def test_valid_hash_rejects_wrong_password(self):
        h = srv.hash_pw("CorrectHorse123!")
        assert srv.verify_pw("WrongPassword", h) is False

    def test_none_hash_never_raises(self):
        # This used to raise AttributeError/ValueError before hardening.
        assert srv.verify_pw("anything", None) is False

    def test_empty_string_hash_never_raises(self):
        assert srv.verify_pw("anything", "") is False

    def test_garbage_string_hash_never_raises(self):
        # This is the exact class of bug from the Render logs:
        # ValueError: Invalid salt — a non-empty but non-bcrypt string.
        for garbage in ["not-a-hash", "plaintext-password", "sha256:abc123", "12345"]:
            assert srv.verify_pw("anything", garbage) is False

    def test_truncated_bcrypt_hash_never_raises(self):
        real = srv.hash_pw("SomePassword123!")
        truncated = real[:20]  # corrupt/truncated — still starts with $2b$ but malformed
        assert srv.verify_pw("SomePassword123!", truncated) is False


class TestIsValidBcryptHash:
    def test_real_hash_is_valid(self):
        assert srv.is_valid_bcrypt_hash(srv.hash_pw("x")) is True

    @pytest.mark.parametrize("bad", [None, "", "abc", "$2b$only-prefix", "a" * 60])
    def test_invalid_values(self, bad):
        assert srv.is_valid_bcrypt_hash(bad) is False


class TestPasswordReuseGuard:
    def test_skips_corrupt_history_without_crashing(self):
        good_old_hash = srv.hash_pw("OldPassword123!")
        user = {
            "password": srv.hash_pw("CurrentPassword123!"),
            # Simulates legacy/corrupt data mixed into history — must not crash.
            "password_history": ["", None, "not-a-real-hash", good_old_hash],
        }
        # Reusing the genuinely-old password should still be caught.
        with pytest.raises(srv.HTTPException):
            srv._reject_if_password_reused("OldPassword123!", user)
        # A brand-new password should sail through with no exception.
        srv._reject_if_password_reused("BrandNewPassword456!", user)

    def test_google_oauth_user_with_no_password_field(self):
        # Google-OAuth-only accounts have no "password" key at all.
        user = {"password_history": []}
        srv._reject_if_password_reused("AnyNewPassword123!", user)  # must not raise


class TestHistoryEntryHelper:
    def test_valid_hash_kept(self):
        h = srv.hash_pw("x")
        assert srv._history_entry(h) == [h]

    @pytest.mark.parametrize("bad", [None, "", "garbage"])
    def test_invalid_values_dropped(self, bad):
        assert srv._history_entry(bad) == []


# ============================================================
# 2) Integration — OTP-based reset (real OTP via otp_service, no email needed)
# ============================================================
class TestOtpResetFlow:
    def _seed_otp(self, email: str) -> tuple:
        """Bypasses email delivery — calls the same otp_service.create() the
        real endpoint uses, so we get the real plaintext code for testing."""
        loop = asyncio.get_event_loop()
        user = loop.run_until_complete(srv.db.users.find_one({"email": email}, {"_id": 0}))
        session_id, code = loop.run_until_complete(
            otp_service.create(srv.db, purpose="reset-password", email=email, payload={"user_id": user["user_id"]})
        )
        return session_id, code

    def test_full_otp_reset_round_trip(self):
        email = f"TEST_otp_reset_{uuid.uuid4().hex[:8]}@example.com"
        old_pw, new_pw = "Initial123!", "BrandNewSecret456!"
        _register_temp(email, old_pw)
        try:
            session_id, code = self._seed_otp(email)
            r = requests.post(f"{API}/auth/reset-password/otp/verify",
                               json={"otp_session": session_id, "code": code, "new_password": new_pw},
                               timeout=15)
            assert r.status_code == 200, r.text

            r_old = requests.post(f"{API}/auth/login", json={"email": email, "password": old_pw}, timeout=15)
            assert r_old.status_code == 401

            r_new = requests.post(f"{API}/auth/login", json={"email": email, "password": new_pw}, timeout=15)
            assert r_new.status_code == 200, r_new.text
        finally:
            _delete_user(email)

    def test_wrong_code_rejected(self):
        email = f"TEST_otp_wrong_{uuid.uuid4().hex[:8]}@example.com"
        _register_temp(email)
        try:
            session_id, _ = self._seed_otp(email)
            r = requests.post(f"{API}/auth/reset-password/otp/verify",
                               json={"otp_session": session_id, "code": "000000", "new_password": "Whatever123!"},
                               timeout=15)
            assert r.status_code == 400
        finally:
            _delete_user(email)

    def test_already_consumed_retry_is_idempotent_success(self):
        """Simulates the Render-cold-start double-submit case: the same OTP
        session is verified twice. The second call must succeed (not error)
        since the password was already correctly updated by the first call."""
        email = f"TEST_otp_retry_{uuid.uuid4().hex[:8]}@example.com"
        _register_temp(email)
        try:
            session_id, code = self._seed_otp(email)
            body = {"otp_session": session_id, "code": code, "new_password": "RetrySafe789!"}
            r1 = requests.post(f"{API}/auth/reset-password/otp/verify", json=body, timeout=15)
            assert r1.status_code == 200, r1.text

            r2 = requests.post(f"{API}/auth/reset-password/otp/verify", json=body, timeout=15)
            assert r2.status_code == 200, f"retry on already-consumed OTP should succeed gracefully: {r2.text}"

            r_login = requests.post(f"{API}/auth/login", json={"email": email, "password": "RetrySafe789!"}, timeout=15)
            assert r_login.status_code == 200
        finally:
            _delete_user(email)


# ============================================================
# 3) Integration — Email-link reset: reused password rejected end-to-end
# ============================================================
class TestEmailLinkReuseRejection:
    def test_cannot_reset_to_current_password(self):
        email = f"TEST_link_reuse_{uuid.uuid4().hex[:8]}@example.com"
        pw = "SamePassword123!"
        _register_temp(email, pw)
        try:
            loop = asyncio.get_event_loop()
            user = loop.run_until_complete(srv.db.users.find_one({"email": email}, {"_id": 0}))
            token = "TEST_" + uuid.uuid4().hex
            from datetime import datetime, timedelta, timezone
            loop.run_until_complete(srv.db.password_reset_tokens.insert_one({
                "token": token, "user_id": user["user_id"], "email": email,
                "expires_at": datetime.now(timezone.utc) + timedelta(minutes=15),
                "used": False, "created_at": srv.now_iso(),
            }))
            r = requests.post(f"{API}/auth/reset-password", json={"token": token, "new_password": pw}, timeout=15)
            assert r.status_code == 400
            assert "used this password before" in r.json().get("detail", "").lower()
        finally:
            loop = asyncio.get_event_loop()
            loop.run_until_complete(srv.db.password_reset_tokens.delete_many({"email": email}))
            _delete_user(email)
