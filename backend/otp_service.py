"""OTP generation, hashing, verification, and rate-limiting.

Contract:
- 6-digit numeric OTP, generated with `secrets.randbelow`
- Stored as bcrypt hash in `otp_verifications` collection — the plain code
  never touches disk after generation
- TTL: 10 minutes from creation
- Resend cooldown: 60 seconds between resend requests for the same session
- Max 5 verify attempts per session; further attempts return 429 until TTL
- One-time use: on successful verify the record is deleted immediately

The collection holds a snapshot of the pending registration payload so the
`verify-otp` endpoint can atomically create the user after checking the code.

Schema (`otp_verifications`):
  otp_session   str, unique index
  purpose       str  — "register" | "reset-password" | ...
  email         str
  code_hash     str  (bcrypt)
  attempts      int
  resend_count  int
  last_sent_at  ISO string
  expires_at    ISO string (server-side gate)
  payload       dict — role, name, phone, location, password_hash
"""
from __future__ import annotations
import os
import logging
import secrets
import uuid
from datetime import datetime, timezone, timedelta

import bcrypt

logger = logging.getLogger(__name__)

OTP_TTL = timedelta(minutes=int(os.environ.get("OTP_TTL_MINUTES", "10")))
RESEND_COOLDOWN = timedelta(seconds=int(os.environ.get("OTP_RESEND_COOLDOWN", "60")))
MAX_ATTEMPTS = int(os.environ.get("OTP_MAX_ATTEMPTS", "5"))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def generate_code() -> str:
    """Return a 6-digit zero-padded numeric OTP."""
    return f"{secrets.randbelow(1_000_000):06d}"


def _hash_code(code: str) -> str:
    return bcrypt.hashpw(code.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _verify_code(code: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(code.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


async def ensure_indexes(db) -> None:
    await db.otp_verifications.create_index("otp_session", unique=True)
    await db.otp_verifications.create_index("email")
    # Mongo TTL — clears rows 60s after expiry (rest is handled by our own gate).
    # Using an ISO string field precludes the built-in TTL index; expiry checks
    # happen in code below.


async def create(db, *, purpose: str, email: str, payload: dict) -> tuple[str, str]:
    """Create a new OTP session and return (session_id, code).
    The plain code is returned ONLY to the caller so it can be delivered
    (e.g., emailed). It is never stored."""
    email = email.lower().strip()
    session_id = f"otp_{uuid.uuid4().hex[:16]}"
    code = generate_code()
    now = _now()
    doc = {
        "otp_session": session_id,
        "purpose": purpose,
        "email": email,
        "code_hash": _hash_code(code),
        "attempts": 0,
        "resend_count": 0,
        "last_sent_at": _iso(now),
        "expires_at": _iso(now + OTP_TTL),
        "created_at": _iso(now),
        "payload": payload,
    }
    await db.otp_verifications.insert_one(doc)
    return session_id, code


async def resend(db, *, session_id: str) -> tuple[str, dict]:
    """Rotate the OTP for an existing session (enforces 60s cooldown).
    Returns (new_code, session_doc). Raises ValueError on cooldown / expiry."""
    row = await db.otp_verifications.find_one({"otp_session": session_id}, {"_id": 0})
    if not row:
        raise ValueError("session_not_found")
    if _parse_iso(row["expires_at"]) < _now():
        raise ValueError("expired")
    last = _parse_iso(row["last_sent_at"])
    delta = _now() - last
    if delta < RESEND_COOLDOWN:
        seconds_left = int((RESEND_COOLDOWN - delta).total_seconds())
        raise ValueError(f"cooldown:{seconds_left}")

    new_code = generate_code()
    now = _now()
    await db.otp_verifications.update_one(
        {"otp_session": session_id},
        {"$set": {
            "code_hash": _hash_code(new_code),
            "last_sent_at": _iso(now),
            # Reset attempt counter so a new code isn't immediately locked out
            # by prior wrong tries.
            "attempts": 0,
        }, "$inc": {"resend_count": 1}},
    )
    row = await db.otp_verifications.find_one({"otp_session": session_id}, {"_id": 0})
    return new_code, row


async def verify(db, *, session_id: str, code: str) -> dict:
    """Verify a code. On success, DELETE the record and return the payload
    so the caller can create the user. On failure raises ValueError with a
    machine-readable reason."""
    row = await db.otp_verifications.find_one({"otp_session": session_id}, {"_id": 0})
    if not row:
        raise ValueError("session_not_found")
    if _parse_iso(row["expires_at"]) < _now():
        await db.otp_verifications.delete_one({"otp_session": session_id})
        raise ValueError("expired")
    if row["attempts"] >= MAX_ATTEMPTS:
        raise ValueError("too_many_attempts")

    if not _verify_code(code, row["code_hash"]):
        new_attempts = row["attempts"] + 1
        await db.otp_verifications.update_one(
            {"otp_session": session_id}, {"$set": {"attempts": new_attempts}},
        )
        remaining = MAX_ATTEMPTS - new_attempts
        if remaining <= 0:
            raise ValueError("too_many_attempts")
        raise ValueError(f"invalid_code:{remaining}")

    payload = row.get("payload") or {}
    payload["_email"] = row["email"]
    await db.otp_verifications.delete_one({"otp_session": session_id})
    return payload


async def peek(db, *, session_id: str) -> dict | None:
    """Public read — used by the frontend to show TTL. Never returns hash."""
    row = await db.otp_verifications.find_one(
        {"otp_session": session_id},
        {"_id": 0, "code_hash": 0, "payload": 0},
    )
    return row
