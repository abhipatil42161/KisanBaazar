"""Email service — Brevo (Sendinblue) transactional HTTP API with graceful
dev-mock fallback.

- When BREVO_API_KEY is set: sends real email via Brevo's HTTP API
  (POST https://api.brevo.com/v3/smtp/email) using httpx, which is already
  a dependency of this project — no extra SDK/package required.
- When BREVO_API_KEY is empty: logs the email to the backend logger and
  returns success so registration flow still works in dev environments
  without email credentials (matches the Razorpay / Cloudinary graceful-mock
  pattern already in this codebase).
"""
from __future__ import annotations
import os
import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

API_KEY = os.environ.get("BREVO_API_KEY", "").strip()
FROM_EMAIL = os.environ.get(
    "BREVO_FROM_EMAIL",
    os.environ.get("SENDER_EMAIL", "no-reply@kisanbaazar.in"),
).strip()
FROM_NAME = os.environ.get("BREVO_FROM_NAME", "KisanBaazar").strip()

BREVO_ENDPOINT = "https://api.brevo.com/v3/smtp/email"


def is_enabled() -> bool:
    return bool(API_KEY)


async def send_email(
    *, to: str, subject: str, html: str, text: Optional[str] = None,
) -> dict:
    """Send an email. Returns {ok, id?, mock?}. Never raises on transport
    failure — caller is registration flow and we do not want an email-provider
    outage to break signup entirely; we log and continue."""
    if not API_KEY:
        # Dev / mock mode — log with clear marker so the operator can copy
        # the OTP from server logs.
        logger.warning("[EMAIL:MOCK] to=%s subject=%s\n---\n%s\n---", to, subject, text or html)
        return {"ok": True, "mock": True}

    payload = {
        "sender": {"name": FROM_NAME, "email": FROM_EMAIL},
        "to": [{"email": to}],
        "subject": subject,
        "htmlContent": html,
    }
    if text:
        payload["textContent"] = text

    headers = {
        "api-key": API_KEY,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(BREVO_ENDPOINT, json=payload, headers=headers)
        if resp.status_code >= 400:
            logger.error(
                "Brevo send_email failed to=%s status=%s body=%s",
                to, resp.status_code, resp.text,
            )
            return {"ok": False}
        data = resp.json() if resp.content else {}
        return {"ok": True, "id": data.get("messageId")}
    except Exception:
        logger.exception("Brevo send_email failed to=%s", to)
        return {"ok": False}
