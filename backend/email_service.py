"""Email service — Resend transport with graceful dev-mock fallback.

- When RESEND_API_KEY is set: sends real email via Resend's SDK (called via
  asyncio.to_thread since the SDK is synchronous).
- When RESEND_API_KEY is empty: logs the email to the backend logger and
  returns success so registration flow still works in dev environments
  without email credentials (matches the Razorpay / Cloudinary graceful-mock
  pattern already in this codebase).
"""
from __future__ import annotations
import os
import asyncio
import logging
from typing import Optional

import resend

logger = logging.getLogger(__name__)

API_KEY = os.environ.get("RESEND_API_KEY", "").strip()
FROM_EMAIL = os.environ.get(
    "RESEND_FROM_EMAIL",
    os.environ.get("SENDER_EMAIL", "onboarding@resend.dev"),
).strip()

_configured = False


def is_enabled() -> bool:
    return bool(API_KEY)


def _configure_once() -> None:
    global _configured
    if _configured:
        return
    if API_KEY:
        resend.api_key = API_KEY
    _configured = True


async def send_email(
    *, to: str, subject: str, html: str, text: Optional[str] = None,
) -> dict:
    """Send an email. Returns {ok, id?, mock?}. Never raises on transport
    failure — caller is registration flow and we do not want a Resend outage
    to break signup entirely; we log and continue."""
    _configure_once()
    if not API_KEY:
        # Dev / mock mode — log with clear marker so the operator can copy
        # the OTP from server logs.
        logger.warning("[EMAIL:MOCK] to=%s subject=%s\n---\n%s\n---", to, subject, text or html)
        return {"ok": True, "mock": True}

    params = {
        "from": FROM_EMAIL,
        "to": [to],
        "subject": subject,
        "html": html,
    }
    if text:
        params["text"] = text
    try:
        # resend.Emails.send is synchronous — offload to the default executor
        # to keep FastAPI's event loop non-blocking.
        result = await asyncio.to_thread(resend.Emails.send, params)
        eid = result.get("id") if isinstance(result, dict) else None
        return {"ok": True, "id": eid}
    except Exception:
        logger.exception("Resend send_email failed to=%s", to)
        return {"ok": False}
