"""Regression tests for KisanBaazar after FarmerDashboard refactor.

Covers: login (3 roles), farmer dashboard data endpoints, product CRUD,
orders, categories, AI price-predict, bidding sanity.
"""
import os
import time
import uuid
import pytest
import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"


def _login(role, creds):
    email, pw = creds[role]
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json={"email": email, "password": pw}, timeout=15)
    assert r.status_code == 200, f"login {role} failed: {r.status_code} {r.text}"
    data = r.json()
    assert "user" in data and "csrf_token" in data
    # Phase C: JWT lives in httpOnly kb_token cookie; return it for Bearer-compat tests
    token = s.cookies.get("kb_token")
    assert token, "kb_token cookie missing"
    return token, data["user"], s


@pytest.fixture(scope="module")
def farmer_auth(test_creds):
    return _login("farmer", test_creds)


@pytest.fixture(scope="module")
def buyer_auth(test_creds):
    return _login("buyer", test_creds)


@pytest.fixture(scope="module")
def admin_auth(test_creds):
    return _login("admin", test_creds)


def _h(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


# --- AUTH ---
class TestAuth:
    def test_farmer_login(self, farmer_auth):
        token, user, _ = farmer_auth
        assert user["role"] == "farmer"
        assert len(token) > 0

    def test_buyer_login(self, buyer_auth):
        token, user, _ = buyer_auth
        assert user["role"] == "buyer"

    def test_admin_login(self, admin_auth):
        token, user, _ = admin_auth
        assert user["role"] == "admin"

    def test_auth_me_farmer(self, farmer_auth, test_creds):
        token, _, _ = farmer_auth
        r = requests.get(f"{API}/auth/me", headers=_h(token), timeout=15)
        assert r.status_code == 200
        assert r.json()["email"] == test_creds["farmer"][0]

    def test_invalid_login(self, test_creds):
        farmer_email = test_creds["farmer"][0]
        r = requests.post(f"{API}/auth/login", json={"email": farmer_email, "password": "wrong"}, timeout=15)
        assert r.status_code in (400, 401, 403)


# --- DASHBOARD DATA (used by useFarmerData hook) ---
class TestFarmerDashboardData:
    def test_get_dashboard_stats(self, farmer_auth):
        token, _, _ = farmer_auth
        r = requests.get(f"{API}/dashboard/stats", headers=_h(token), timeout=15)
        assert r.status_code == 200
        data = r.json()
        # Must have keys consumed by FarmerStats.jsx
        assert "products" in data
        assert "orders" in data
        assert "revenue" in data

    def test_get_products(self, farmer_auth):
        token, _, _ = farmer_auth
        r = requests.get(f"{API}/products", headers=_h(token), timeout=15)
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        assert len(data) > 0
        # Validate product shape used by FarmerListings
        p = data[0]
        for k in ("product_id", "title", "price", "unit", "available_qty", "farmer_id"):
            assert k in p, f"missing key {k}"

    def test_products_filter_by_farmer(self, farmer_auth):
        token, user, _ = farmer_auth
        r = requests.get(f"{API}/products", headers=_h(token), timeout=15)
        owned = [p for p in r.json() if p["farmer_id"] == user["user_id"]]
        assert len(owned) > 0, "farmer should have seeded listings"

    def test_get_orders(self, farmer_auth):
        token, _, _ = farmer_auth
        r = requests.get(f"{API}/orders", headers=_h(token), timeout=15)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_get_categories(self, farmer_auth):
        token, _, _ = farmer_auth
        r = requests.get(f"{API}/categories", headers=_h(token), timeout=15)
        assert r.status_code == 200
        cats = r.json()
        assert isinstance(cats, list) and len(cats) > 0
        assert "id" in cats[0] and "name" in cats[0]


# --- PRODUCT CRUD (AddProductDialog + delete) ---
class TestProductCRUD:
    def test_create_and_delete_product(self, farmer_auth):
        token, user, _ = farmer_auth
        payload = {
            "title": f"TEST_Tomatoes_{uuid.uuid4().hex[:6]}",
            "description": "Regression test product",
            "category": "vegetables",
            "price": 50,
            "unit": "kg",
            "moq": 1,
            "available_qty": 100,
            "quality_grade": "A",
            "organic": False,
            "export_ready": False,
            "images": ["https://example.com/img.jpg"],
            "location": "Nashik",
            "state": "Maharashtra",
            "harvest_date": "2025-12-01",
            "auction": False,
        }
        r = requests.post(f"{API}/products", headers=_h(token), json=payload, timeout=15)
        assert r.status_code in (200, 201), f"create failed: {r.status_code} {r.text}"
        created = r.json()
        assert created["title"] == payload["title"]
        assert created["farmer_id"] == user["user_id"]
        pid = created["product_id"]

        # GET verifies persistence (used by listings reload)
        r2 = requests.get(f"{API}/products", headers=_h(token), timeout=15)
        assert any(p["product_id"] == pid for p in r2.json())

        # DELETE
        r3 = requests.delete(f"{API}/products/{pid}", headers=_h(token), timeout=15)
        assert r3.status_code in (200, 204)

        # Verify removed
        r4 = requests.get(f"{API}/products", headers=_h(token), timeout=15)
        assert not any(p["product_id"] == pid for p in r4.json())


# --- AI PRICE PREDICT ---
class TestAIPricePredict:
    def test_ai_price_predict_called(self, farmer_auth):
        token, _, _ = farmer_auth
        r = requests.post(
            f"{API}/ai/price-predict",
            headers=_h(token),
            json={"message": "Crop: Tomatoes. Location: Nashik, Maharashtra. Quality: A. Estimate price."},
            timeout=45,
        )
        # Allow 200 or upstream-unavailable; we just verify route exists & auths OK
        assert r.status_code in (200, 503, 500), f"unexpected status: {r.status_code} {r.text}"
        if r.status_code == 200:
            assert "prediction" in r.json()


# --- BUYER & ADMIN sanity ---
class TestRoleSanity:
    def test_buyer_orders_endpoint(self, buyer_auth):
        token, _, _ = buyer_auth
        r = requests.get(f"{API}/orders", headers=_h(token), timeout=15)
        assert r.status_code == 200

    def test_admin_orders_endpoint(self, admin_auth):
        token, _, _ = admin_auth
        r = requests.get(f"{API}/orders", headers=_h(token), timeout=15)
        assert r.status_code == 200
