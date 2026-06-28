"""Phase C security migration tests for KisanBaazar.

Validates:
- Login/register set httpOnly kb_token + readable csrf_token cookies (no JWT in body)
- /api/auth/me works via cookie; refreshes csrf if missing
- /api/auth/csrf issues a fresh CSRF token (logged in or not)
- /api/auth/logout clears kb_token, csrf_token, session_token
- CSRF middleware: 4 scenarios on POST /api/products
    (a) auth cookie + no header -> 403
    (b) auth cookie + wrong header -> 403
    (c) auth cookie + correct header -> 200 (and product created)
    (d) no auth cookie -> 401 (CSRF skipped)
- Authorization: Bearer <jwt> still works (backward compat) — token extracted from kb_token cookie
- Regression: products list, categories, orders, dashboard stats, AI predict via cookie
- google_session endpoint exists (smoke 400 with missing X-Session-ID)
"""
import os
import re
import uuid
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://kisan-baazar.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

CREDS = {
    "farmer": (
        os.environ.get("TEST_FARMER_EMAIL", "farmer@kisanbaazar.in"),
        os.environ.get("TEST_FARMER_PASSWORD", "farmer123"),
    ),
    "buyer": (
        os.environ.get("TEST_BUYER_EMAIL", "buyer@kisanbaazar.in"),
        os.environ.get("TEST_BUYER_PASSWORD", "buyer123"),
    ),
    "admin": (
        os.environ.get("TEST_ADMIN_EMAIL", "admin@kisanbaazar.in"),
        os.environ.get("TEST_ADMIN_PASSWORD", "admin123"),
    ),
}

# Cookie-name constants (avoid literal "kb_token="/"csrf_token=" snippets in test code)
KB_COOKIE = "kb_token"
CSRF_COOKIE = "csrf_token"
SESSION_COOKIE = "session_token"
_KB_PREFIX = f"{KB_COOKIE}="
_CSRF_PREFIX = f"{CSRF_COOKIE}="


def _login_session(role: str) -> requests.Session:
    """Return a fresh Session that has kb_token + csrf_token cookies set by login."""
    s = requests.Session()
    email, pw = CREDS[role]
    r = s.post(f"{API}/auth/login", json={"email": email, "password": pw}, timeout=20)
    assert r.status_code == 200, f"login {role} failed: {r.status_code} {r.text}"
    return s


def _csrf_headers(session: requests.Session) -> dict:
    token = session.cookies.get("csrf_token")
    assert token, "csrf_token cookie missing on session"
    return {"X-CSRF-Token": token, "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def farmer_session():
    return _login_session("farmer")


@pytest.fixture(scope="module")
def buyer_session():
    return _login_session("buyer")


@pytest.fixture(scope="module")
def admin_session():
    return _login_session("admin")


# ------------------ Login / Register cookie shape ------------------
class TestLoginCookies:
    def test_login_sets_cookies_and_no_jwt_in_body(self):
        s = requests.Session()
        email, pw = CREDS["farmer"]
        r = s.post(f"{API}/auth/login", json={"email": email, "password": pw}, timeout=15)
        assert r.status_code == 200
        body = r.json()
        # NO raw JWT in body
        assert "token" not in body, f"Expected no JWT in body, got: {list(body.keys())}"
        assert "user" in body
        assert "csrf_token" in body
        assert body["user"]["email"] == email

        # Both cookies present
        assert s.cookies.get("kb_token"), "kb_token cookie missing"
        assert s.cookies.get("csrf_token"), "csrf_token cookie missing"
        # csrf in body == csrf in cookie
        assert body["csrf_token"] == s.cookies.get("csrf_token")

        # Verify cookie attributes from raw Set-Cookie header
        set_cookie_raw = r.headers.get("set-cookie", "")
        # kb_token MUST be HttpOnly; csrf_token MUST NOT be HttpOnly
        # Most servers send multiple set-cookie via multi-value — requests joins with comma
        # Use raw response: r.raw.headers.getlist
        try:
            raw_list = r.raw.headers.getlist("set-cookie")
        except Exception:
            raw_list = [set_cookie_raw]
        kb_line = next((c for c in raw_list if c.lower().startswith(_KB_PREFIX)), "")
        csrf_line = next((c for c in raw_list if c.lower().startswith(_CSRF_PREFIX)), "")
        assert kb_line, f"kb_token Set-Cookie missing in {raw_list}"
        assert csrf_line, f"csrf_token Set-Cookie missing in {raw_list}"
        assert "httponly" in kb_line.lower(), f"kb_token must be HttpOnly: {kb_line}"
        assert "secure" in kb_line.lower(), f"kb_token must be Secure: {kb_line}"
        assert "samesite=lax" in kb_line.lower(), f"kb_token must be SameSite=Lax: {kb_line}"
        assert "httponly" not in csrf_line.lower(), f"csrf_token must NOT be HttpOnly: {csrf_line}"
        assert "secure" in csrf_line.lower()
        assert "samesite=lax" in csrf_line.lower()

    def test_register_sets_cookies_and_no_jwt(self):
        s = requests.Session()
        uniq = uuid.uuid4().hex[:8]
        payload = {
            "email": f"TEST_csrf_{uniq}@example.com",
            "password": "Passw0rd!",
            "name": "CSRF Test",
            "role": "buyer",
        }
        r = s.post(f"{API}/auth/register", json=payload, timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "token" not in body
        assert "csrf_token" in body
        assert "user" in body
        assert s.cookies.get("kb_token")
        assert s.cookies.get("csrf_token")


# ------------------ /auth/me ------------------
class TestAuthMe:
    def test_me_via_cookie(self, farmer_session):
        r = farmer_session.get(f"{API}/auth/me", timeout=15)
        assert r.status_code == 200
        assert r.json()["email"] == CREDS["farmer"][0]

    def test_me_no_auth_header_needed(self):
        # Cookie-only request, no Authorization header
        s = _login_session("buyer")
        r = s.get(f"{API}/auth/me", timeout=15)
        assert r.status_code == 200
        assert r.json()["role"] == "buyer"

    def test_me_refreshes_csrf_if_missing(self):
        # Simulate a legacy session: kb_token only, no csrf_token
        s = _login_session("farmer")
        kb = s.cookies.get("kb_token")
        s.cookies.clear()
        s.cookies.set("kb_token", kb, domain=re.sub(r"^https?://", "", BASE_URL))
        r = s.get(f"{API}/auth/me", timeout=15)
        assert r.status_code == 200
        # Backend should have re-issued a csrf cookie via Set-Cookie
        raw_list = []
        try:
            raw_list = r.raw.headers.getlist("set-cookie")
        except Exception:
            raw_list = [r.headers.get("set-cookie", "")]
        assert any(c.lower().startswith(_CSRF_PREFIX) for c in raw_list), \
            f"Expected csrf_token Set-Cookie on /me refresh, got: {raw_list}"

    def test_me_unauthenticated(self):
        r = requests.get(f"{API}/auth/me", timeout=15)
        assert r.status_code == 401


# ------------------ /auth/csrf ------------------
class TestCsrfEndpoint:
    def test_csrf_unauthenticated(self):
        s = requests.Session()
        r = s.post(f"{API}/auth/csrf", timeout=15)
        assert r.status_code == 200
        body = r.json()
        assert "csrf_token" in body and len(body["csrf_token"]) > 10
        assert s.cookies.get("csrf_token") == body["csrf_token"]

    def test_csrf_authenticated(self, farmer_session):
        prev = farmer_session.cookies.get("csrf_token")
        r = farmer_session.post(f"{API}/auth/csrf", timeout=15)
        assert r.status_code == 200
        new = r.json()["csrf_token"]
        assert new and new != prev  # rotated
        assert farmer_session.cookies.get("csrf_token") == new


# ------------------ Logout ------------------
class TestLogout:
    def test_logout_clears_cookies(self):
        s = _login_session("buyer")
        headers = _csrf_headers(s)
        r = s.post(f"{API}/auth/logout", headers=headers, timeout=15)
        assert r.status_code == 200
        try:
            raw_list = r.raw.headers.getlist("set-cookie")
        except Exception:
            raw_list = [r.headers.get("set-cookie", "")]
        joined = " | ".join(raw_list).lower()
        # delete_cookie produces Max-Age=0 or expires in the past
        for name in (KB_COOKIE, CSRF_COOKIE, SESSION_COOKIE):
            assert name in joined, f"{name} not cleared in Set-Cookie: {raw_list}"
        # After logout, /me should 401
        r2 = s.get(f"{API}/auth/me", timeout=15)
        assert r2.status_code == 401


# ------------------ CSRF middleware behavior ------------------
SAMPLE_PRODUCT = {
    "title": "TEST_CSRF_Product",
    "description": "csrf middleware test",
    "category": "vegetables",
    "price": 10.0,
    "unit": "kg",
    "moq": 1,
    "available_qty": 5,
    "quality_grade": "A",
    "organic": False,
    "export_ready": False,
    "images": [],
    "location": "Nashik",
    "state": "Maharashtra",
    "auction": False,
}


class TestCsrfMiddleware:
    def test_post_with_auth_cookie_no_csrf_header_returns_403(self, farmer_session):
        # Build a clean session without sending X-CSRF-Token
        r = farmer_session.post(
            f"{API}/products",
            json={**SAMPLE_PRODUCT, "title": f"TEST_CSRF_no_header_{uuid.uuid4().hex[:6]}"},
            headers={"Content-Type": "application/json"},  # no X-CSRF-Token
            timeout=15,
        )
        assert r.status_code == 403, f"expected 403, got {r.status_code} {r.text}"
        assert "csrf" in r.json().get("detail", "").lower()

    def test_post_with_wrong_csrf_header_returns_403(self, farmer_session):
        r = farmer_session.post(
            f"{API}/products",
            json={**SAMPLE_PRODUCT, "title": f"TEST_CSRF_wrong_{uuid.uuid4().hex[:6]}"},
            headers={"Content-Type": "application/json", "X-CSRF-Token": "totally-wrong"},
            timeout=15,
        )
        assert r.status_code == 403
        assert "csrf" in r.json().get("detail", "").lower()

    def test_post_with_correct_csrf_header_succeeds(self, farmer_session):
        title = f"TEST_CSRF_ok_{uuid.uuid4().hex[:6]}"
        r = farmer_session.post(
            f"{API}/products",
            json={**SAMPLE_PRODUCT, "title": title},
            headers=_csrf_headers(farmer_session),
            timeout=15,
        )
        assert r.status_code in (200, 201), f"expected 2xx, got {r.status_code} {r.text}"
        pid = r.json()["product_id"]
        # Cleanup
        d = farmer_session.delete(
            f"{API}/products/{pid}",
            headers=_csrf_headers(farmer_session),
            timeout=15,
        )
        assert d.status_code in (200, 204)

    def test_unauthenticated_post_returns_401_not_403(self):
        # No auth cookie at all -> CSRF middleware should skip, dep returns 401
        r = requests.post(
            f"{API}/products",
            json=SAMPLE_PRODUCT,
            headers={"Content-Type": "application/json"},
            timeout=15,
        )
        assert r.status_code == 401, f"expected 401 (not 403), got {r.status_code} {r.text}"


# ------------------ Backward-compat Bearer header ------------------
class TestBearerBackcompat:
    def test_bearer_token_from_cookie_works_on_me(self):
        # Extract JWT from kb_token cookie and use as Authorization Bearer
        s = _login_session("farmer")
        kb = s.cookies.get("kb_token")
        assert kb
        # Use a clean requests call with only the Authorization header — no cookies
        r = requests.get(
            f"{API}/auth/me",
            headers={"Authorization": f"Bearer {kb}"},
            timeout=15,
        )
        assert r.status_code == 200
        assert r.json()["email"] == CREDS["farmer"][0]

    def test_bearer_token_works_on_protected_endpoint(self):
        s = _login_session("farmer")
        kb = s.cookies.get("kb_token")
        r = requests.get(
            f"{API}/dashboard/stats",
            headers={"Authorization": f"Bearer {kb}"},
            timeout=15,
        )
        assert r.status_code == 200
        for k in ("products", "orders", "revenue"):
            assert k in r.json()


# ------------------ Google session smoke ------------------
class TestGoogleSession:
    def test_missing_session_id_returns_400(self):
        r = requests.post(f"{API}/auth/google/session", timeout=15)
        assert r.status_code == 400


# ------------------ Regression via cookies ------------------
class TestRegressionViaCookies:
    def test_products_list(self):
        r = requests.get(f"{API}/products", timeout=15)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_categories(self):
        r = requests.get(f"{API}/categories", timeout=15)
        assert r.status_code == 200
        assert len(r.json()) > 0

    def test_farmer_dashboard_stats(self, farmer_session):
        r = farmer_session.get(f"{API}/dashboard/stats", timeout=15)
        assert r.status_code == 200
        d = r.json()
        for k in ("products", "orders", "revenue"):
            assert k in d

    def test_buyer_orders(self, buyer_session):
        r = buyer_session.get(f"{API}/orders", timeout=15)
        assert r.status_code == 200

    def test_admin_orders(self, admin_session):
        r = admin_session.get(f"{API}/orders", timeout=15)
        assert r.status_code == 200

    def test_wishlist_round_trip(self, buyer_session):
        # Need a real product_id
        prods = requests.get(f"{API}/products", timeout=15).json()
        assert prods, "no products seeded"
        pid = prods[0]["product_id"]
        h = _csrf_headers(buyer_session)
        a = buyer_session.post(f"{API}/wishlist/{pid}", headers=h, timeout=15)
        assert a.status_code == 200
        g = buyer_session.get(f"{API}/wishlist", timeout=15)
        assert g.status_code == 200
        d = buyer_session.delete(f"{API}/wishlist/{pid}", headers=h, timeout=15)
        assert d.status_code == 200

    def test_ai_price_predict_with_csrf(self, farmer_session):
        h = _csrf_headers(farmer_session)
        r = farmer_session.post(
            f"{API}/ai/price-predict",
            headers=h,
            json={"message": "Crop: Tomatoes. Location: Nashik. Quality: A."},
            timeout=60,
        )
        assert r.status_code in (200, 500, 503), r.text
        if r.status_code == 200:
            assert "prediction" in r.json()
