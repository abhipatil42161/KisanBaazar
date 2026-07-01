"""Ratings & Reviews service.

Implements the full review lifecycle:
- create (gated on paid order ownership + one-per-order)
- update (buyer edits own review)
- farmer reply (one reply per review)
- report (any auth user)
- admin moderate (publish / hide / delete)
- denormalised aggregates on `products` (rating_avg, rating_count) and
  on `users` (farmer_rating_avg, farmer_rating_count) — re-computed on every
  status-affecting change so listings stay fast.
"""
from __future__ import annotations
import uuid
from datetime import datetime, timezone
from typing import Iterable, Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def ensure_indexes(db) -> None:
    """One-time indexes — called at startup."""
    # One review per (buyer, order) — buyers can only review once per order.
    await db.reviews.create_index([("order_id", 1), ("buyer_id", 1)], unique=True)
    await db.reviews.create_index("product_id")
    await db.reviews.create_index("farmer_id")
    await db.reviews.create_index("status")
    await db.reviews.create_index("created_at")


async def buyer_can_review(db, *, order_id: str, product_id: str, buyer_id: str) -> Optional[dict]:
    """Returns the matching order doc if the buyer is allowed to leave a
    review for `product_id` from `order_id`, else None.

    Eligibility:
    - order belongs to buyer
    - order.payment_status == "paid"
    - product_id is in the order's items
    - no existing review for this (order, buyer)
    """
    order = await db.orders.find_one({"order_id": order_id}, {"_id": 0})
    if not order:
        return None
    if order.get("buyer_id") != buyer_id:
        return None
    if order.get("payment_status") != "paid":
        return None
    if not any(it.get("product_id") == product_id for it in order.get("items", [])):
        return None
    existing = await db.reviews.find_one(
        {"order_id": order_id, "buyer_id": buyer_id, "product_id": product_id},
        {"_id": 0, "review_id": 1},
    )
    if existing:
        return None
    return order


async def _recompute_product_rating(db, product_id: str) -> None:
    cur = db.reviews.aggregate([
        {"$match": {"product_id": product_id, "status": "published"}},
        {"$group": {"_id": "$product_id", "avg": {"$avg": "$rating"}, "n": {"$sum": 1}}},
    ])
    docs = await cur.to_list(1)
    avg = round(docs[0]["avg"], 2) if docs else 0.0
    count = docs[0]["n"] if docs else 0
    await db.products.update_one(
        {"product_id": product_id},
        {"$set": {"rating_avg": avg, "rating_count": count}},
    )


async def _recompute_farmer_rating(db, farmer_id: str) -> None:
    cur = db.reviews.aggregate([
        {"$match": {"farmer_id": farmer_id, "status": "published"}},
        {"$group": {"_id": "$farmer_id", "avg": {"$avg": "$rating"}, "n": {"$sum": 1}}},
    ])
    docs = await cur.to_list(1)
    avg = round(docs[0]["avg"], 2) if docs else 0.0
    count = docs[0]["n"] if docs else 0
    await db.users.update_one(
        {"user_id": farmer_id},
        {"$set": {"farmer_rating_avg": avg, "farmer_rating_count": count}},
    )


async def recompute_aggregates(db, *, product_id: str, farmer_id: str) -> None:
    """Recompute product + farmer rating aggregates. Called from every mutation."""
    await _recompute_product_rating(db, product_id)
    await _recompute_farmer_rating(db, farmer_id)


async def create_review(
    db, *,
    buyer_id: str, buyer_name: str,
    order_id: str, product_id: str,
    rating: int, title: str, body: str, images: Iterable[dict],
) -> dict:
    """Create a review (gating must be checked by the caller via buyer_can_review).
    Returns the inserted review document.
    """
    order = await buyer_can_review(
        db, order_id=order_id, product_id=product_id, buyer_id=buyer_id
    )
    if not order:
        raise ValueError("not_eligible")
    prod = await db.products.find_one({"product_id": product_id}, {"_id": 0, "farmer_id": 1})
    if not prod:
        raise ValueError("product_not_found")
    if not (1 <= int(rating) <= 5):
        raise ValueError("invalid_rating")
    doc = {
        "review_id": f"rev_{uuid.uuid4().hex[:12]}",
        "order_id": order_id,
        "product_id": product_id,
        "farmer_id": prod["farmer_id"],
        "buyer_id": buyer_id,
        "buyer_name": buyer_name,
        "rating": int(rating),
        "title": (title or "")[:120],
        "body": (body or "")[:2000],
        "images": list(images or []),
        "verified_purchase": True,
        "status": "published",
        "reply": None,
        "reports": [],
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    await db.reviews.insert_one(doc)
    await recompute_aggregates(db, product_id=product_id, farmer_id=prod["farmer_id"])
    doc.pop("_id", None)
    return doc


async def update_review(
    db, *, review_id: str, buyer_id: str,
    rating: Optional[int] = None, title: Optional[str] = None,
    body: Optional[str] = None, images: Optional[Iterable[dict]] = None,
) -> dict:
    rev = await db.reviews.find_one({"review_id": review_id}, {"_id": 0})
    if not rev:
        raise ValueError("not_found")
    if rev["buyer_id"] != buyer_id:
        raise ValueError("forbidden")
    upd: dict = {"updated_at": _now_iso()}
    if rating is not None:
        if not (1 <= int(rating) <= 5):
            raise ValueError("invalid_rating")
        upd["rating"] = int(rating)
    if title is not None:
        upd["title"] = title[:120]
    if body is not None:
        upd["body"] = body[:2000]
    if images is not None:
        upd["images"] = list(images)
    await db.reviews.update_one({"review_id": review_id}, {"$set": upd})
    if "rating" in upd:
        await recompute_aggregates(
            db, product_id=rev["product_id"], farmer_id=rev["farmer_id"]
        )
    return await db.reviews.find_one({"review_id": review_id}, {"_id": 0})


async def reply_to_review(
    db, *, review_id: str, farmer_id: str, body: str,
) -> dict:
    rev = await db.reviews.find_one({"review_id": review_id}, {"_id": 0})
    if not rev:
        raise ValueError("not_found")
    if rev["farmer_id"] != farmer_id:
        raise ValueError("forbidden")
    if rev.get("reply"):
        raise ValueError("already_replied")
    reply = {
        "farmer_id": farmer_id,
        "body": (body or "")[:1000],
        "created_at": _now_iso(),
    }
    await db.reviews.update_one(
        {"review_id": review_id}, {"$set": {"reply": reply, "updated_at": _now_iso()}}
    )
    return await db.reviews.find_one({"review_id": review_id}, {"_id": 0})


async def report_review(
    db, *, review_id: str, reporter_id: str, reason: str,
) -> dict:
    rev = await db.reviews.find_one({"review_id": review_id}, {"_id": 0})
    if not rev:
        raise ValueError("not_found")
    # No double-reporting from the same user.
    if any(r.get("user_id") == reporter_id for r in (rev.get("reports") or [])):
        raise ValueError("already_reported")
    report = {
        "user_id": reporter_id,
        "reason": (reason or "inappropriate")[:200],
        "created_at": _now_iso(),
    }
    await db.reviews.update_one(
        {"review_id": review_id},
        {"$push": {"reports": report}, "$set": {"status": "reported", "updated_at": _now_iso()}},
    )
    # Recompute aggregates because "reported" reviews drop out of "published".
    await recompute_aggregates(
        db, product_id=rev["product_id"], farmer_id=rev["farmer_id"]
    )
    return await db.reviews.find_one({"review_id": review_id}, {"_id": 0})


async def moderate_review(
    db, *, review_id: str, action: str,
) -> Optional[dict]:
    """Admin action. action in {publish, hide, delete}."""
    rev = await db.reviews.find_one({"review_id": review_id}, {"_id": 0})
    if not rev:
        raise ValueError("not_found")
    if action == "delete":
        await db.reviews.delete_one({"review_id": review_id})
        await recompute_aggregates(
            db, product_id=rev["product_id"], farmer_id=rev["farmer_id"]
        )
        return None
    if action not in ("publish", "hide"):
        raise ValueError("invalid_action")
    new_status = "published" if action == "publish" else "hidden"
    await db.reviews.update_one(
        {"review_id": review_id},
        {"$set": {"status": new_status, "updated_at": _now_iso()}},
    )
    await recompute_aggregates(
        db, product_id=rev["product_id"], farmer_id=rev["farmer_id"]
    )
    return await db.reviews.find_one({"review_id": review_id}, {"_id": 0})
