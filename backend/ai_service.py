"""AI service — production-compatible Anthropic Claude client.

Replaces the internal `emergentintegrations` package (not on PyPI) with the
official `anthropic` SDK so the backend can be deployed to Render / any
standard Python host.

- `ANTHROPIC_API_KEY` is read from env. `EMERGENT_LLM_KEY` is honoured as a
  fallback name so existing environments keep working.
- Session memory: prior turns are loaded from the `chat_messages` MongoDB
  collection by `session_id`, matching the old `LlmChat` behaviour.
- Graceful degradation: when no key is configured, endpoints return a
  friendly notice instead of 500-ing.
"""
from __future__ import annotations
import os
import logging
from typing import AsyncIterator, List, Optional

from anthropic import AsyncAnthropic
from anthropic import APIError

logger = logging.getLogger(__name__)

MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929")
API_KEY = (
    os.environ.get("ANTHROPIC_API_KEY", "").strip()
    or os.environ.get("EMERGENT_LLM_KEY", "").strip()
)

_client: Optional[AsyncAnthropic] = None


def is_enabled() -> bool:
    return bool(API_KEY)


def _client_or_none() -> Optional[AsyncAnthropic]:
    global _client
    if not API_KEY:
        return None
    client = _client
    if client is None:
        client = AsyncAnthropic(api_key=API_KEY)
        _client = client
    return client


async def _history_for_session(db, session_id: str, limit: int = 12) -> List[dict]:
    """Load recent turns for this session and format for Anthropic's messages API."""
    if not session_id:
        return []
    cur = db.chat_messages.find(
        {"session_id": session_id}, {"_id": 0, "user_msg": 1, "ai_msg": 1}
    ).sort("created_at", -1).limit(limit)
    rows = await cur.to_list(limit)
    rows.reverse()
    msgs: List[dict] = []
    for r in rows:
        if r.get("user_msg"):
            msgs.append({"role": "user", "content": r["user_msg"]})
        if r.get("ai_msg"):
            msgs.append({"role": "assistant", "content": r["ai_msg"]})
    return msgs


async def stream_reply(
    *,
    db,
    session_id: Optional[str],
    system: str,
    user_message: str,
) -> AsyncIterator[str]:
    """Async generator yielding text chunks from Claude. Includes session history
    when `session_id` is provided. If AI is not configured, yields a single
    fallback string instead of raising."""
    client = _client_or_none()
    if client is None:
        yield "AI is not configured on this deployment. Set ANTHROPIC_API_KEY to enable it."
        return

    history = await _history_for_session(db, session_id or "")
    history.append({"role": "user", "content": user_message})

    try:
        async with client.messages.stream(
            model=MODEL,
            max_tokens=1024,
            system=system,
            messages=history,
        ) as stream:
            async for chunk in stream.text_stream:
                yield chunk
    except APIError as e:
        logger.exception("Anthropic API error")
        yield f"\n[AI error: {e.__class__.__name__}]"
    except Exception as e:
        logger.exception("AI stream failed")
        yield f"\n[error: {e.__class__.__name__}]"


async def one_shot(*, system: str, user_message: str) -> str:
    """Non-streaming helper used by /ai/price-predict."""
    client = _client_or_none()
    if client is None:
        return "AI is not configured on this deployment. Set ANTHROPIC_API_KEY to enable it."
    try:
        resp = await client.messages.create(
            model=MODEL,
            max_tokens=512,
            system=system,
            messages=[{"role": "user", "content": user_message}],
        )
        parts = [b.text for b in resp.content if getattr(b, "type", "") == "text"]
        return "".join(parts).strip() or "No prediction available."
    except Exception as e:
        logger.exception("one_shot AI failed")
        return f"Suggested: market range varies. Please check local mandi rates. (AI temporarily unavailable: {type(e).__name__})"
