"""Razorpay integration tests.

Covers:
- GET /api/payments/config returns enabled flag (no secret leak)
- POST /api/orders for non-COD method produces razorpay_order_id and razorpay_amount_paise
- POST /api/orders for COD does NOT hit the gateway (razorpay_order_id is None)
- POST /api/orders/{oid}/verify rejects bad signature with 400 + marks order failed
- razorpay_service.verify_payment_signature unit test (HMAC math)
- razorpay_service.verify_webhook_signature unit test
- /api/orders/{oid}/pay is forbidden when real Razorpay is enabled for non-COD orders
"""
import os
import sys
import hmac
import hashlib
import uuid
from pathlib import Path
import pytest
import requests

# Allow tests to import backend modules directly (razorpay_service, etc.).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"


def _login(role, creds):
    email, pw = creds[role]
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json={"email": email, "password": pw}, timeout=15)
    assert r.status_code == 200, f"login {role}: {r.text}"
    return s, r.json()


def _csrf(session, payload):
    return {"X-CSRF-Token": session.cookies.get("csrf_token"), **(payload or {})}


@pytest.fixture(scope="module")
def buyer_session(test_creds):
    s, _ = _login("buyer", test_creds)
    return s


def _place_order(session, items=None, method="upi"):
    items = items or [{
        "product_id": f"test_prod_{uuid.uuid4().hex[:6]}",
        "title": "Test Tomato",
        "qty": 2,
        "price": 50.0,
        "image": "",
    }]
    r = session.post(
        f"{API}/orders",
        json={
            "items": items,
            "delivery_address": "Test addr · Phone: 9999999999",
            "payment_method": method,
        },
        headers={"X-CSRF-Token": session.cookies.get("csrf_token")},
        timeout=15,
    )
    return r


# ---------- Public payment config ----------
class TestPaymentConfig:
    def test_config_endpoint_safe(self):
        r = requests.get(f"{API}/payments/config", timeout=10)
        assert r.status_code == 200
        body = r.json()
        assert "enabled" in body
        assert "key_id" in body
        # If enabled, key_id must be a public key (starts with rzp_); if disabled, must be null/empty.
        if body["enabled"]:
            assert body["key_id"] and body["key_id"].startswith("rzp_")
        else:
            assert not body["key_id"]
        # Defense: secret keys must NEVER appear in this payload.
        assert "key_secret" not in body
        assert "secret" not in body


# ---------- Order create wires Razorpay id ----------
class TestOrderRazorpayId:
    def test_non_cod_order_has_razorpay_id(self, buyer_session):
        r = _place_order(buyer_session, method="upi")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["razorpay_order_id"], "razorpay_order_id should be set for non-COD"
        assert body["razorpay_amount_paise"] > 0
        assert body["payment_status"] == "pending"

    def test_cod_order_has_no_razorpay_id(self, buyer_session):
        r = _place_order(buyer_session, method="cod")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["razorpay_order_id"] in (None, ""), "COD must not create a gateway order"
        assert body["razorpay_amount_paise"] == 0
        assert body["payment_method"] == "cod"

    def test_charge_total_applies_one_percent_fee(self, buyer_session):
        items = [{"product_id": "test_x", "title": "X", "qty": 1, "price": 1000.0, "image": ""}]
        r = _place_order(buyer_session, items=items, method="upi")
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 1000  # subtotal preserved
        assert body["charge_total"] == 1010  # 1% fee
        assert body["razorpay_amount_paise"] == 101000


# ---------- Verify endpoint rejects bad signature ----------
class TestVerifyRejection:
    def test_bad_signature_marks_order_failed(self, buyer_session):
        r = _place_order(buyer_session, method="upi")
        assert r.status_code == 200
        order = r.json()
        oid = order["order_id"]
        bad = {
            "razorpay_order_id": order["razorpay_order_id"],
            "razorpay_payment_id": f"pay_test_{uuid.uuid4().hex[:10]}",
            "razorpay_signature": "deadbeef" * 8,
        }
        v = buyer_session.post(
            f"{API}/orders/{oid}/verify",
            json=bad,
            headers={"X-CSRF-Token": buyer_session.cookies.get("csrf_token")},
            timeout=15,
        )
        # When Razorpay is disabled the helper returns False → still 400.
        assert v.status_code == 400

    def test_verify_unknown_order_404(self, buyer_session):
        v = buyer_session.post(
            f"{API}/orders/ord_does_not_exist/verify",
            json={"razorpay_order_id": "x", "razorpay_payment_id": "y", "razorpay_signature": "z"},
            headers={"X-CSRF-Token": buyer_session.cookies.get("csrf_token")},
            timeout=15,
        )
        assert v.status_code == 404


# ---------- Webhook signature verification ----------
class TestWebhookSignature:
    def test_webhook_rejects_unsigned(self):
        r = requests.post(f"{API}/payments/webhook", json={"event": "payment.captured"}, timeout=10)
        # Either rejected (400) when secret configured, OR rejected with 400 when not (empty signature)
        assert r.status_code == 400

    def test_webhook_signature_helper_math(self):
        """Direct unit test on the verifier — independent of env keys."""
        # Reload module against a known secret.
        os.environ["RAZORPAY_WEBHOOK_SECRET"] = "unit_test_secret"
        from importlib import reload
        import razorpay_service
        reload(razorpay_service)
        body = b'{"event":"payment.captured"}'
        good = hmac.new(b"unit_test_secret", body, hashlib.sha256).hexdigest()
        assert razorpay_service.verify_webhook_signature(body, good)
        assert not razorpay_service.verify_webhook_signature(body, "x" + good[1:])
        assert not razorpay_service.verify_webhook_signature(b"", good)
        assert not razorpay_service.verify_webhook_signature(body, "")


# ---------- Payment signature math (unit) ----------
class TestPaymentSignatureMath:
    def test_signature_verify_local(self):
        """The Razorpay payment_signature is HMAC-SHA256(order_id|payment_id, secret).
        We can validate this end-to-end against the SDK without touching the network."""
        os.environ["RAZORPAY_KEY_ID"] = "rzp_test_unit"
        os.environ["RAZORPAY_KEY_SECRET"] = "unit_secret"
        from importlib import reload
        import razorpay_service
        reload(razorpay_service)
        oid = "order_abc123"
        pid = "pay_xyz456"
        good = hmac.new(b"unit_secret", f"{oid}|{pid}".encode(), hashlib.sha256).hexdigest()
        assert razorpay_service.verify_payment_signature(oid, pid, good)
        assert not razorpay_service.verify_payment_signature(oid, pid, "0" * 64)
        assert not razorpay_service.verify_payment_signature("", pid, good)


# ---------- Mock-pay guard rails ----------
class TestMockPayGuard:
    def test_mock_pay_works_when_gateway_disabled_or_cod(self, buyer_session):
        """If real Razorpay is NOT configured, /pay (mock) finalises the order.
        If real Razorpay IS configured, /pay (mock) is allowed only for COD orders."""
        cfg = requests.get(f"{API}/payments/config", timeout=10).json()
        # Use a COD order — always allowed via /pay regardless of gateway state.
        r = _place_order(buyer_session, method="cod")
        oid = r.json()["order_id"]
        p = buyer_session.post(
            f"{API}/orders/{oid}/pay",
            headers={"X-CSRF-Token": buyer_session.cookies.get("csrf_token")},
            timeout=15,
        )
        assert p.status_code == 200
        assert p.json()["ok"]
        # If gateway disabled, non-COD mock-pay should also work
        if not cfg["enabled"]:
            r2 = _place_order(buyer_session, method="upi")
            oid2 = r2.json()["order_id"]
            p2 = buyer_session.post(
                f"{API}/orders/{oid2}/pay",
                headers={"X-CSRF-Token": buyer_session.cookies.get("csrf_token")},
                timeout=15,
            )
            assert p2.status_code == 200
        else:
            r2 = _place_order(buyer_session, method="upi")
            oid2 = r2.json()["order_id"]
            p2 = buyer_session.post(
                f"{API}/orders/{oid2}/pay",
                headers={"X-CSRF-Token": buyer_session.cookies.get("csrf_token")},
                timeout=15,
            )
            assert p2.status_code == 400
