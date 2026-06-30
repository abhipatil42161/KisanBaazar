"""Post-payment business workflow.

Centralises everything that must happen exactly once when a payment is
captured: persist a `payments` row, decrement product stock, mark the order
paid+confirmed, and fan out in-app notifications to the buyer + each farmer
whose product is in the cart.

The whole flow is **idempotent** — calling `finalise_paid_order()` twice for
the same `razorpay_payment_id` is a no-op the second time. This protects
against duplicate execution from the success handler AND a concurrent webhook.
"""
from __future__ import annotations
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def ensure_indexes(db) -> None:
    """One-shot index creation. Called at FastAPI startup."""
    await db.payments.create_index("razorpay_payment_id", unique=True, sparse=True)
    await db.payments.create_index("order_id")
    await db.payments.create_index("user_id")
    await db.payments.create_index("created_at")
    await db.notifications.create_index([("user_id", 1), ("read", 1), ("created_at", -1)])


async def _create_notification(db, user_id: str, kind: str, title: str, body: str, link: str = "") -> None:
    if not user_id:
        return
    await db.notifications.insert_one({
        "notification_id": f"ntf_{uuid.uuid4().hex[:12]}",
        "user_id": user_id,
        "kind": kind,
        "title": title,
        "body": body,
        "link": link,
        "read": False,
        "created_at": _now_iso(),
    })


async def finalise_paid_order(
    db,
    *,
    order: dict,
    razorpay_payment_id: str,
    razorpay_signature: Optional[str],
    amount_paise: int,
    currency: str = "INR",
    source: str = "verify",  # "verify" | "webhook" | "mock"
    method: Optional[str] = None,
) -> dict:
    """Idempotently mark an order paid + persist a payment row + reduce stock
    + notify all involved parties. Safe to call multiple times — returns the
    existing payment row on subsequent calls.
    """
    # 1) Idempotency: have we already finalised this payment?
    existing = await db.payments.find_one(
        {"razorpay_payment_id": razorpay_payment_id}, {"_id": 0}
    )
    if existing:
        return existing

    oid = order["order_id"]

    # 2) Insert the payment row (unique on razorpay_payment_id — race-safe).
    payment_doc = {
        "payment_id": f"pmt_{uuid.uuid4().hex[:12]}",
        "razorpay_payment_id": razorpay_payment_id,
        "razorpay_order_id": order.get("razorpay_order_id"),
        "razorpay_signature": razorpay_signature,
        "order_id": oid,
        "user_id": order["buyer_id"],
        "buyer_name": order.get("buyer_name"),
        "amount": amount_paise / 100,
        "amount_paise": amount_paise,
        "currency": currency,
        "method": method or order.get("payment_method"),
        "status": "captured",
        "source": source,
        "refund_id": None,
        "refund_amount_paise": 0,
        "refunded_at": None,
        "settlement_status": "pending",
        "created_at": _now_iso(),
    }
    try:
        await db.payments.insert_one(payment_doc)
    except Exception:
        # Almost certainly a duplicate-key race — re-fetch and return.
        existing = await db.payments.find_one(
            {"razorpay_payment_id": razorpay_payment_id}, {"_id": 0}
        )
        if existing:
            return existing
        raise

    # 3) Atomically mark the order paid + flag stock-deducted so concurrent
    #    calls can't double-debit.
    upd = await db.orders.update_one(
        {"order_id": oid, "stock_deducted": {"$ne": True}},
        {"$set": {
            "payment_status": "paid",
            "status": "confirmed",
            "razorpay_payment_id": razorpay_payment_id,
            "razorpay_signature": razorpay_signature,
            "paid_at": _now_iso(),
            "stock_deducted": True,
        }},
    )

    # 4) If WE were the writer that flipped stock_deducted -> decrement stock.
    if upd.modified_count == 1:
        for it in order.get("items", []):
            pid = it.get("product_id")
            qty = int(it.get("qty") or 0)
            if pid and qty > 0:
                await db.products.update_one(
                    {"product_id": pid},
                    {"$inc": {"available_qty": -qty}},
                )

    # 5) Notify buyer + every farmer whose product is in the cart.
    await _create_notification(
        db,
        user_id=order["buyer_id"],
        kind="payment.captured",
        title="Payment received",
        body=f"₹{amount_paise / 100:,.2f} paid for order {oid}. Invoice ready.",
        link=f"/dashboard/buyer?order={oid}",
    )
    farmer_ids: set[str] = set()
    for it in order.get("items", []):
        prod = await db.products.find_one(
            {"product_id": it.get("product_id")}, {"_id": 0, "farmer_id": 1}
        )
        if prod and prod.get("farmer_id"):
            farmer_ids.add(prod["farmer_id"])
    for fid in farmer_ids:
        await _create_notification(
            db,
            user_id=fid,
            kind="payment.captured",
            title="New paid order",
            body=f"You have a new paid order ({oid}). Pack & ship to the buyer.",
            link=f"/dashboard/farmer?order={oid}",
        )

    return payment_doc


async def mark_payment_failed(
    db, *, order: dict, razorpay_payment_id: Optional[str], reason: Optional[str] = None
) -> None:
    """Record a failed-payment audit row + notify buyer (idempotent on
    razorpay_payment_id when present)."""
    if razorpay_payment_id:
        existing = await db.payments.find_one(
            {"razorpay_payment_id": razorpay_payment_id}, {"_id": 0}
        )
        if existing:
            return
    await db.payments.insert_one({
        "payment_id": f"pmt_{uuid.uuid4().hex[:12]}",
        "razorpay_payment_id": razorpay_payment_id,
        "razorpay_order_id": order.get("razorpay_order_id"),
        "order_id": order["order_id"],
        "user_id": order["buyer_id"],
        "buyer_name": order.get("buyer_name"),
        "amount": order.get("charge_total") or order.get("total") or 0,
        "amount_paise": order.get("razorpay_amount_paise") or 0,
        "currency": "INR",
        "method": order.get("payment_method"),
        "status": "failed",
        "failure_reason": reason or "unknown",
        "created_at": _now_iso(),
    })
    await db.orders.update_one(
        {"order_id": order["order_id"]},
        {"$set": {"payment_status": "failed"}},
    )
    await _create_notification(
        db,
        user_id=order["buyer_id"],
        kind="payment.failed",
        title="Payment failed",
        body=f"Your payment for order {order['order_id']} failed. You can retry from your dashboard.",
        link="/dashboard/buyer",
    )


async def record_refund(
    db,
    *,
    razorpay_payment_id: str,
    refund_id: str,
    amount_paise: int,
    status: str,
) -> Optional[dict]:
    """Update the payment row + restock items + notify buyer."""
    payment = await db.payments.find_one(
        {"razorpay_payment_id": razorpay_payment_id}, {"_id": 0}
    )
    if not payment:
        logger.warning("Refund %s for unknown payment %s", refund_id, razorpay_payment_id)
        return None

    already_refunded = payment.get("refund_id") == refund_id
    await db.payments.update_one(
        {"razorpay_payment_id": razorpay_payment_id},
        {"$set": {
            "status": "refunded" if status == "processed" else f"refund_{status}",
            "refund_id": refund_id,
            "refund_amount_paise": int(amount_paise),
            "refunded_at": _now_iso(),
        }},
    )
    # Restore stock + flip the order to cancelled once per refund event.
    if not already_refunded and payment.get("order_id"):
        order = await db.orders.find_one({"order_id": payment["order_id"]}, {"_id": 0})
        if order:
            await db.orders.update_one(
                {"order_id": order["order_id"]},
                {"$set": {"status": "cancelled", "payment_status": "refunded"}},
            )
            for it in order.get("items", []):
                pid = it.get("product_id")
                qty = int(it.get("qty") or 0)
                if pid and qty > 0:
                    await db.products.update_one(
                        {"product_id": pid},
                        {"$inc": {"available_qty": qty}},
                    )
            await _create_notification(
                db,
                user_id=order["buyer_id"],
                kind="refund.processed",
                title="Refund processed",
                body=f"₹{amount_paise / 100:,.2f} refunded for order {order['order_id']}.",
                link="/dashboard/buyer",
            )
    return await db.payments.find_one(
        {"razorpay_payment_id": razorpay_payment_id}, {"_id": 0}
    )
