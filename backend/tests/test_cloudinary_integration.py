"""Cloudinary signed-upload + product cascade-delete integration tests.

Verifies:
 - GET /api/cloudinary/signature (auth, folder validation, payload shape)
 - Direct signed upload to api.cloudinary.com/v1_1/<cloud>/image/upload
 - POST /api/products preserves images as objects
 - DELETE /api/products/{pid} cascades Cloudinary asset removal
 - DELETE /api/cloudinary/image owner/admin permissions
 - PUT /api/products/{pid} partial update + orphan cascade
 - Backwards-compat with string-URL images
"""
import io
import os
import time
import base64
import struct
import zlib
import pytest
import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
CLOUD_NAME = "xuo2ru3u"
UPLOAD_URL = f"https://api.cloudinary.com/v1_1/{CLOUD_NAME}/image/upload"
CDN_BASE = f"https://res.cloudinary.com/{CLOUD_NAME}/image/upload"


# ---- Helpers -----------------------------------------------------------------

def _login(email: str, password: str) -> requests.Session:
    """Login and return a session with kb_token + csrf_token cookies set."""
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, f"login failed for {email}: {r.status_code} {r.text}"
    csrf = s.cookies.get("csrf_token")
    if csrf:
        s.headers.update({"X-CSRF-Token": csrf})
    return s


def _tiny_png_bytes() -> bytes:
    """Build a valid 1x1 transparent PNG in-memory (no PIL dep)."""
    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)  # 1x1 RGBA
    raw = b"\x00" + b"\x00\x00\x00\x00"  # 1 filter byte + RGBA pixel
    idat = zlib.compress(raw)
    return sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


@pytest.fixture(scope="module")
def farmer_sess(test_creds):
    return _login(*test_creds["farmer"])


@pytest.fixture(scope="module")
def buyer_sess(test_creds):
    return _login(*test_creds["buyer"])


@pytest.fixture(scope="module")
def admin_sess(test_creds):
    return _login(*test_creds["admin"])


# ---- Tests: signature endpoint ----------------------------------------------

class TestSignatureEndpoint:
    def test_signature_authenticated(self, farmer_sess):
        r = farmer_sess.get(f"{BASE_URL}/api/cloudinary/signature")
        assert r.status_code == 200, r.text
        d = r.json()
        # Required keys
        for k in ("signature", "timestamp", "api_key", "cloud_name", "folder", "max_bytes", "allowed_formats"):
            assert k in d, f"missing key {k}"
        assert d["cloud_name"] == "xuo2ru3u"
        # Folder is now per-user scoped: kisanbaazar/products/user_<id>
        assert d["folder"].startswith("kisanbaazar/products/user_"), d["folder"]
        assert d["max_bytes"] == 10 * 1024 * 1024
        assert sorted(d["allowed_formats"]) == ["jpeg", "jpg", "png", "webp"]
        # sha1 hex string
        assert isinstance(d["signature"], str) and len(d["signature"]) == 40
        int(d["signature"], 16)  # validates hex
        # timestamp is recent (within 60s)
        assert abs(int(d["timestamp"]) - int(time.time())) < 60

    def test_signature_unauthenticated_401(self):
        r = requests.get(f"{BASE_URL}/api/cloudinary/signature")
        assert r.status_code == 401

    def test_signature_invalid_folder_400(self, farmer_sess):
        r = farmer_sess.get(f"{BASE_URL}/api/cloudinary/signature", params={"folder": "evil/path"})
        assert r.status_code == 400


# ---- Tests: direct signed upload + product CRUD ------------------------------

@pytest.fixture(scope="module")
def uploaded_asset(farmer_sess):
    """Sign + upload a real tiny PNG to Cloudinary. Yields {secure_url, public_id, ...}."""
    sig = farmer_sess.get(f"{BASE_URL}/api/cloudinary/signature").json()
    files = {"file": ("tiny.png", _tiny_png_bytes(), "image/png")}
    data = {
        "api_key": sig["api_key"],
        "timestamp": str(sig["timestamp"]),
        "signature": sig["signature"],
        "folder": sig["folder"],
    }
    r = requests.post(UPLOAD_URL, files=files, data=data, timeout=30)
    assert r.status_code == 200, f"direct upload failed: {r.status_code} {r.text}"
    j = r.json()
    assert j["secure_url"].startswith("https://res.cloudinary.com/xuo2ru3u/")
    assert j["public_id"].startswith("kisanbaazar/products/")
    assert "width" in j and "height" in j
    return {
        "secure_url": j["secure_url"],
        "public_id": j["public_id"],
        "width": j["width"],
        "height": j["height"],
    }


class TestSignedUploadAndProduct:
    def test_direct_upload_works(self, uploaded_asset):
        assert uploaded_asset["public_id"].startswith("kisanbaazar/products/")

    def test_product_create_with_image_objects(self, farmer_sess, uploaded_asset):
        payload = {
            "title": "TEST_Cloudinary Onion",
            "description": "Test product for cloudinary integration",
            "category": "vegetables",
            "price": 25.0,
            "unit": "kg",
            "moq": 10,
            "available_qty": 500,
            "quality_grade": "A",
            "organic": False,
            "export_ready": False,
            "images": [uploaded_asset],
            "location": "Pune",
            "state": "Maharashtra",
            "harvest_date": "2026-01-01",
        }
        r = farmer_sess.post(f"{BASE_URL}/api/products", json=payload)
        assert r.status_code in (200, 201), r.text
        prod = r.json()
        assert "product_id" in prod
        assert isinstance(prod["images"], list) and len(prod["images"]) == 1
        img = prod["images"][0]
        assert img["public_id"] == uploaded_asset["public_id"]
        assert img["secure_url"] == uploaded_asset["secure_url"]
        # stash for later tests in module via class attribute pattern
        pytest._kb_test_pid = prod["product_id"]
        pytest._kb_test_public_id = uploaded_asset["public_id"]
        pytest._kb_test_secure_url = uploaded_asset["secure_url"]


# ---- Tests: PUT partial update + orphan cascade ------------------------------

class TestPartialUpdateAndOrphanCascade:
    def test_put_partial_only_title(self, farmer_sess):
        pid = getattr(pytest, "_kb_test_pid", None)
        if not pid:
            pytest.skip("requires prior product create")
        r = farmer_sess.put(f"{BASE_URL}/api/products/{pid}", json={"title": "TEST_Updated Title"})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["title"] == "TEST_Updated Title"
        # images should still be present (not wiped)
        assert isinstance(d["images"], list) and len(d["images"]) == 1

    def test_put_images_orphan_cascade(self, farmer_sess):
        """Upload a 2nd image, replace product images with just it -> first should be deleted from Cloudinary."""
        pid = getattr(pytest, "_kb_test_pid", None)
        first_public_id = getattr(pytest, "_kb_test_public_id", None)
        if not (pid and first_public_id):
            pytest.skip("requires prior product create")

        # Upload a fresh asset
        sig = farmer_sess.get(f"{BASE_URL}/api/cloudinary/signature").json()
        files = {"file": ("tiny2.png", _tiny_png_bytes(), "image/png")}
        data = {
            "api_key": sig["api_key"],
            "timestamp": str(sig["timestamp"]),
            "signature": sig["signature"],
            "folder": sig["folder"],
        }
        ur = requests.post(UPLOAD_URL, files=files, data=data, timeout=30).json()
        new_asset = {
            "secure_url": ur["secure_url"],
            "public_id": ur["public_id"],
            "width": ur["width"],
            "height": ur["height"],
        }

        # PUT: replace images with just the new one
        r = farmer_sess.put(f"{BASE_URL}/api/products/{pid}", json={"images": [new_asset]})
        assert r.status_code == 200, r.text
        assert len(r.json()["images"]) == 1
        assert r.json()["images"][0]["public_id"] == new_asset["public_id"]

        # Verify the orphaned first image is gone from Cloudinary CDN (poll up to ~12s)
        orphan_url = f"{CDN_BASE}/{first_public_id}.png"
        gone = False
        for _ in range(12):
            time.sleep(1)
            hd = requests.get(orphan_url, timeout=10)
            if hd.status_code in (404, 401, 403):
                gone = True
                break
        assert gone, f"orphan {first_public_id} still resolves at {orphan_url}"

        # Track the remaining asset for delete-cascade test
        pytest._kb_test_public_id = new_asset["public_id"]
        pytest._kb_test_secure_url = new_asset["secure_url"]


# ---- Tests: DELETE /api/cloudinary/image permissions -------------------------

class TestCloudinaryDeletePermissions:
    def test_buyer_cannot_delete_others_asset(self, buyer_sess):
        public_id = getattr(pytest, "_kb_test_public_id", None)
        if not public_id:
            pytest.skip("requires uploaded asset")
        r = buyer_sess.delete(
            f"{BASE_URL}/api/cloudinary/image",
            json={"public_id": public_id},
        )
        assert r.status_code == 403, r.text

    def test_admin_can_delete_arbitrary_then_owner_reuploads(self, admin_sess, farmer_sess):
        """Admin can delete any public_id. Farmer can delete their OWN orphan (post-fix)."""
        # Upload a fresh standalone asset as farmer (but not attached to any product)
        sig = farmer_sess.get(f"{BASE_URL}/api/cloudinary/signature").json()
        files = {"file": ("admin_del.png", _tiny_png_bytes(), "image/png")}
        data = {
            "api_key": sig["api_key"],
            "timestamp": str(sig["timestamp"]),
            "signature": sig["signature"],
            "folder": sig["folder"],
        }
        ur = requests.post(UPLOAD_URL, files=files, data=data, timeout=30).json()
        pub_id = ur["public_id"]

        # POST-FIX: Farmer CAN delete their own orphan because public_id lives under their user folder
        r1 = farmer_sess.delete(f"{BASE_URL}/api/cloudinary/image", json={"public_id": pub_id})
        assert r1.status_code == 200, f"farmer should be able to delete own orphan asset post-fix: {r1.text}"
        assert r1.json().get("ok")

        # Upload another orphan as farmer to verify admin-can-delete-others-orphan path
        ur2 = requests.post(UPLOAD_URL, files={"file": ("admin_del2.png", _tiny_png_bytes(), "image/png")}, data=data, timeout=30).json()
        pub_id2 = ur2["public_id"]
        r2 = admin_sess.delete(f"{BASE_URL}/api/cloudinary/image", json={"public_id": pub_id2})
        assert r2.status_code == 200, r2.text
        assert r2.json()["ok"]

    def test_cross_user_cannot_delete_others_orphan(self, farmer_sess, buyer_sess):
        """Buyer must NOT be able to delete farmer's orphan (ownership fix is per-user folder, not permissive)."""
        sig = farmer_sess.get(f"{BASE_URL}/api/cloudinary/signature").json()
        files = {"file": ("cross.png", _tiny_png_bytes(), "image/png")}
        data = {
            "api_key": sig["api_key"],
            "timestamp": str(sig["timestamp"]),
            "signature": sig["signature"],
            "folder": sig["folder"],
        }
        ur = requests.post(UPLOAD_URL, files=files, data=data, timeout=30).json()
        pub_id = ur["public_id"]
        r = buyer_sess.delete(f"{BASE_URL}/api/cloudinary/image", json={"public_id": pub_id})
        assert r.status_code == 403, f"cross-user delete must 403: {r.text}"
        # Cleanup as farmer (owner)
        farmer_sess.delete(f"{BASE_URL}/api/cloudinary/image", json={"public_id": pub_id})


# ---- Tests: product DELETE cascade -------------------------------------------

class TestProductDeleteCascade:
    def test_delete_product_cascades_cloudinary(self, farmer_sess):
        pid = getattr(pytest, "_kb_test_pid", None)
        public_id = getattr(pytest, "_kb_test_public_id", None)
        if not (pid and public_id):
            pytest.skip("requires prior product")
        r = farmer_sess.delete(f"{BASE_URL}/api/products/{pid}")
        assert r.status_code == 200, r.text
        # CDN should 404 within ~12s
        url = f"{CDN_BASE}/{public_id}.png"
        gone = False
        for _ in range(12):
            time.sleep(1)
            hd = requests.get(url, timeout=10)
            if hd.status_code in (404, 401, 403):
                gone = True
                break
        assert gone, f"cascaded image still alive at {url}"

        # And the product itself is 404
        gr = farmer_sess.get(f"{BASE_URL}/api/products/{pid}")
        assert gr.status_code == 404


# ---- Tests: backwards-compat with string-URL images --------------------------

class TestStringUrlBackwardsCompat:
    def test_string_url_images_pass_through(self, farmer_sess):
        payload = {
            "title": "TEST_LegacyStringImages",
            "description": "Backwards-compat check",
            "category": "vegetables",
            "price": 10.0,
            "unit": "kg",
            "moq": 5,
            "available_qty": 100,
            "quality_grade": "A",
            "organic": False,
            "export_ready": False,
            "images": ["https://images.unsplash.com/photo-test"],
            "location": "Nashik",
            "state": "Maharashtra",
            "harvest_date": "2026-01-01",
        }
        r = farmer_sess.post(f"{BASE_URL}/api/products", json=payload)
        assert r.status_code in (200, 201), r.text
        prod = r.json()
        assert prod["images"] == ["https://images.unsplash.com/photo-test"]

        # And GET reflects same
        g = requests.get(f"{BASE_URL}/api/products/{prod['product_id']}")
        assert g.status_code == 200
        assert g.json()["images"] == ["https://images.unsplash.com/photo-test"]

        # Cleanup
        farmer_sess.delete(f"{BASE_URL}/api/products/{prod['product_id']}")
