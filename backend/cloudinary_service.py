"""Cloudinary helpers: signed-upload signatures + server-side delete.

The frontend uploads files directly to Cloudinary using a short-lived signature
generated here. The API secret never leaves the backend. Deletions and any
admin-only operations are performed server-side via cloudinary.uploader.destroy.
"""
from __future__ import annotations
import os
import time
import logging
from typing import Iterable

import cloudinary
import cloudinary.utils
import cloudinary.uploader

logger = logging.getLogger(__name__)

CLOUD_NAME = os.environ.get("CLOUDINARY_CLOUD_NAME")
API_KEY = os.environ.get("CLOUDINARY_API_KEY")
API_SECRET = os.environ.get("CLOUDINARY_API_SECRET")
UPLOAD_FOLDER = os.environ.get("CLOUDINARY_UPLOAD_FOLDER", "kisanbaazar/products")

# Only folders under this prefix are allowed in signed uploads — prevents
# attackers from signing arbitrary paths.
ALLOWED_FOLDER_PREFIX = "kisanbaazar/"
MAX_BYTES = 10 * 1024 * 1024  # 10 MB
ALLOWED_FORMATS = ("jpg", "jpeg", "png", "webp")


def configure() -> bool:
    """Initialise the SDK. Returns False if any credential is missing."""
    if not (CLOUD_NAME and API_KEY and API_SECRET):
        logger.warning("Cloudinary credentials missing — image upload disabled.")
        return False
    cloudinary.config(
        cloud_name=CLOUD_NAME,
        api_key=API_KEY,
        api_secret=API_SECRET,
        secure=True,
    )
    return True


def signature_payload(folder: str | None = None, user_id: str | None = None) -> dict:
    """Return signed params the frontend uses to upload directly to Cloudinary.

    When `user_id` is supplied the asset is scoped to a per-user subfolder so
    the same user can later delete pre-submit (orphan) uploads without needing
    a referencing product row.
    """
    base = (folder or UPLOAD_FOLDER).rstrip("/")
    if user_id:
        # Sanitise: user_id is server-generated (`user_xxxxxxxxxxxx`) so already safe,
        # but keep the regex narrow as defense-in-depth.
        safe_uid = "".join(c for c in user_id if c.isalnum() or c in "_-")[:64]
        if safe_uid:
            base = f"{base}/{safe_uid}"
    if not base.startswith(ALLOWED_FOLDER_PREFIX):
        raise ValueError(f"folder must start with '{ALLOWED_FOLDER_PREFIX}'")
    if not API_SECRET:
        raise RuntimeError("Cloudinary not configured")
    timestamp = int(time.time())
    params_to_sign = {"timestamp": timestamp, "folder": base}
    signature = cloudinary.utils.api_sign_request(params_to_sign, API_SECRET)
    return {
        "signature": signature,
        "timestamp": timestamp,
        "cloud_name": CLOUD_NAME,
        "api_key": API_KEY,
        "folder": base,
        "max_bytes": MAX_BYTES,
        "allowed_formats": list(ALLOWED_FORMATS),
    }


def user_owns_public_id(public_id: str, user_id: str) -> bool:
    """True if a public_id lives under the user's signed-upload subfolder."""
    if not (public_id and user_id):
        return False
    safe_uid = "".join(c for c in user_id if c.isalnum() or c in "_-")[:64]
    return public_id.startswith(f"{UPLOAD_FOLDER.rstrip('/')}/{safe_uid}/")


def delete_image(public_id: str) -> bool:
    """Delete a single Cloudinary asset. Returns True on success or already-gone."""
    if not (public_id and API_SECRET):
        return False
    try:
        res = cloudinary.uploader.destroy(public_id, invalidate=True)
        ok = res.get("result") in ("ok", "not found")
        if not ok:
            logger.warning("Cloudinary destroy returned %s for %s", res, public_id)
        return ok
    except Exception:
        logger.exception("Cloudinary destroy failed for %s", public_id)
        return False


def delete_many(public_ids: Iterable[str]) -> None:
    """Best-effort cascade delete; logs failures but does not raise."""
    for pid in public_ids:
        if pid:
            delete_image(pid)
