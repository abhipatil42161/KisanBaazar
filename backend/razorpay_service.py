"""Razorpay integration helpers.

Real Razorpay is enabled when both RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET are
set in the environment. When they are absent the rest of the codebase falls
back to the MOCK flow already in place — so dev environments without keys
keep working without code changes.

The secret never leaves the backend. The frontend only receives the key_id
(public) plus the server-generated Razorpay order_id.
"""
from __future__ import annotations
import os
import logging
import hmac
import hashlib
from typing import Optional

import razorpay
from razorpay.errors import SignatureVerificationError

logger = logging.getLogger(__name__)

KEY_ID = os.environ.get("RAZORPAY_KEY_ID", "").strip()
KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET", "").strip()
WEBHOOK_SECRET = os.environ.get("RAZORPAY_WEBHOOK_SECRET", "").strip()

_client: Optional[razorpay.Client] = None


def is_enabled() -> bool:
    """Real Razorpay is wired up only when both API credentials are present."""
    return bool(KEY_ID and KEY_SECRET)


def _client_or_raise() -> razorpay.Client:
    global _client
    if not is_enabled():
        raise RuntimeError("Razorpay not configured")
    client = _client
    if client is None:
        client = razorpay.Client(auth=(KEY_ID, KEY_SECRET))
        _client = client
    return client


def public_config() -> dict:
    """Safe payload the frontend can read — never returns the secret."""
    return {"enabled": is_enabled(), "key_id": KEY_ID if is_enabled() else None}


def create_order(amount_paise: int, receipt: str, notes: dict | None = None) -> dict:
    """Create a Razorpay order. amount_paise must be an int (rupees * 100)."""
    if amount_paise <= 0:
        raise ValueError("amount_paise must be > 0")
    client = _client_or_raise()
    # Razorpay receipt cap is 40 chars.
    payload = {
        "amount": int(amount_paise),
        "currency": "INR",
        "receipt": (receipt or "")[:40],
        "payment_capture": 1,
    }
    if notes:
        payload["notes"] = {k: str(v)[:256] for k, v in notes.items() if v is not None}
    order = client.order.create(payload)
    return order


def verify_payment_signature(order_id: str, payment_id: str, signature: str) -> bool:
    """Verify the checkout success handler signature (HMAC-SHA256)."""
    if not (order_id and payment_id and signature and is_enabled()):
        return False
    try:
        _client_or_raise().utility.verify_payment_signature(
            {
                "razorpay_order_id": order_id,
                "razorpay_payment_id": payment_id,
                "razorpay_signature": signature,
            }
        )
        return True
    except SignatureVerificationError:
        return False
    except Exception:
        logger.exception("Razorpay signature verification crashed")
        return False


def verify_webhook_signature(raw_body: bytes, signature_header: str) -> bool:
    """Manual HMAC verification — Razorpay's SDK helper also works but the
    manual implementation avoids the SDK's dependence on a configured client
    when only WEBHOOK_SECRET is set."""
    if not (WEBHOOK_SECRET and signature_header and raw_body):
        return False
    expected = hmac.new(
        WEBHOOK_SECRET.encode("utf-8"), raw_body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header.strip())


def fetch_payment(payment_id: str) -> dict:
    """Fetch a payment entity from Razorpay (used to enrich our records)."""
    return _client_or_raise().payment.fetch(payment_id)


def refund_payment(payment_id: str, amount_paise: int | None = None, notes: dict | None = None) -> dict:
    """Issue a refund. amount_paise=None refunds the full captured amount."""
    payload: dict = {}
    if amount_paise:
        payload["amount"] = int(amount_paise)
    if notes:
        payload["notes"] = {k: str(v)[:256] for k, v in notes.items() if v is not None}
    return _client_or_raise().payment.refund(payment_id, payload)
