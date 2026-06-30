"""KisanBaazar - Agriculture Marketplace Backend."""
from fastapi import FastAPI, APIRouter, HTTPException, Depends, Request, Response, Cookie
from fastapi.responses import StreamingResponse, JSONResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
import uuid
import secrets
import bcrypt
import jwt as pyjwt
import httpx
from pathlib import Path
from pydantic import BaseModel, EmailStr, ConfigDict
from typing import List, Optional, Literal
from datetime import datetime, timezone, timedelta

from emergentintegrations.llm.chat import LlmChat, UserMessage, TextDelta, StreamDone

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

# Import AFTER load_dotenv so module-level os.environ reads see populated values.
from cloudinary_service import (  # noqa: E402
    configure as configure_cloudinary,
    signature_payload as cloudinary_signature_payload,
    delete_image as cloudinary_delete_image,
    delete_many as cloudinary_delete_many,
    user_owns_public_id as cloudinary_user_owns,
)
from razorpay_service import (  # noqa: E402
    is_enabled as razorpay_enabled,
    public_config as razorpay_public_config,
    create_order as razorpay_create_order,
    verify_payment_signature as razorpay_verify_signature,
    verify_webhook_signature as razorpay_verify_webhook,
    refund_payment as razorpay_refund_payment,
)
from payments_service import (  # noqa: E402
    ensure_indexes as ensure_payment_indexes,
    finalise_paid_order,
    mark_payment_failed,
    record_refund,
)
from invoice_service import generate_invoice_pdf  # noqa: E402

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]
JWT_SECRET = os.environ["JWT_SECRET"]
EMERGENT_LLM_KEY = os.environ["EMERGENT_LLM_KEY"]
FRONTEND_URL = os.environ.get("FRONTEND_URL", "*")

# Initialise Cloudinary (no-op if env vars missing — see cloudinary_service)
CLOUDINARY_ENABLED = configure_cloudinary()

client = AsyncIOMotorClient(MONGO_URL)
db = client[DB_NAME]

app = FastAPI(title="KisanBaazar API")
api = APIRouter(prefix="/api")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# ------------------ Cookie / CSRF constants ------------------
AUTH_COOKIE = "kb_token"
SESSION_COOKIE = "session_token"  # legacy Emergent Google session token
CSRF_COOKIE = "csrf_token"
CSRF_HEADER = "X-CSRF-Token"
COOKIE_MAX_AGE = 7 * 24 * 3600  # 7 days
# CSRF is exempt for unauthenticated bootstrap endpoints and SSE streaming
CSRF_EXEMPT_PATHS = {
    "/api/auth/login",
    "/api/auth/register",
    "/api/auth/google/session",
    "/api/auth/csrf",
    "/api/auth/forgot-password",
    "/api/auth/reset-password",
    "/api/payments/webhook",
}

# ------------------ Brute-force / Password reset constants ------------------
LOCK_THRESHOLD = 5
LOCK_DURATION = timedelta(minutes=15)
RESET_TOKEN_TTL = timedelta(hours=1)
MIN_PW_LEN = 6


def _set_auth_cookies(response: Response, jwt_token: str, csrf_value: Optional[str] = None) -> str:
    """Set httpOnly JWT cookie + readable CSRF cookie. Returns the CSRF value used."""
    csrf_value = csrf_value or secrets.token_urlsafe(32)
    response.set_cookie(
        AUTH_COOKIE, jwt_token,
        httponly=True, secure=True, samesite="lax", path="/", max_age=COOKIE_MAX_AGE,
    )
    response.set_cookie(
        CSRF_COOKIE, csrf_value,
        httponly=False, secure=True, samesite="lax", path="/", max_age=COOKIE_MAX_AGE,
    )
    return csrf_value


def _clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(AUTH_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
    response.delete_cookie(SESSION_COOKIE, path="/")


# ------------------ Models ------------------
class User(BaseModel):
    model_config = ConfigDict(extra="ignore")
    user_id: str
    email: str
    name: str
    role: Literal["farmer", "buyer", "exporter", "admin"] = "buyer"
    phone: Optional[str] = None
    location: Optional[str] = None
    picture: Optional[str] = None
    verified: bool = False
    created_at: str


class RegisterReq(BaseModel):
    email: EmailStr
    password: str
    name: str
    role: Literal["farmer", "buyer", "exporter"] = "buyer"
    phone: Optional[str] = None
    location: Optional[str] = None


class LoginReq(BaseModel):
    email: EmailStr
    password: str


class ForgotPasswordReq(BaseModel):
    email: EmailStr


class ResetPasswordReq(BaseModel):
    token: str
    new_password: str


class Product(BaseModel):
    model_config = ConfigDict(extra="ignore")
    product_id: str
    farmer_id: str
    farmer_name: str
    title: str
    description: str
    category: str
    price: float
    unit: str = "kg"
    moq: int = 1
    available_qty: int
    quality_grade: Literal["A", "B", "C", "Export"] = "A"
    organic: bool = False
    export_ready: bool = False
    images: List = []
    location: str
    state: str
    country: str = "India"
    harvest_date: Optional[str] = None
    auction: bool = False
    auction_end: Optional[str] = None
    current_bid: Optional[float] = None
    created_at: str


class ProductCreate(BaseModel):
    title: str
    description: str
    category: str
    price: float
    unit: str = "kg"
    moq: int = 1
    available_qty: int
    quality_grade: Literal["A", "B", "C", "Export"] = "A"
    organic: bool = False
    export_ready: bool = False
    images: List = []
    location: str
    state: str
    country: str = "India"
    harvest_date: Optional[str] = None
    auction: bool = False
    auction_end: Optional[str] = None


class OrderItem(BaseModel):
    product_id: str
    title: str
    qty: int
    price: float
    image: Optional[str] = None


class OrderCreate(BaseModel):
    items: List[OrderItem]
    delivery_address: str
    payment_method: Literal["upi", "card", "netbanking", "wallet", "cod"] = "upi"


class Order(BaseModel):
    model_config = ConfigDict(extra="ignore")
    order_id: str
    buyer_id: str
    buyer_name: str
    items: List[OrderItem]
    total: float
    charge_total: Optional[float] = None
    delivery_address: str
    payment_method: str
    payment_status: Literal["pending", "paid", "failed"] = "pending"
    status: Literal["placed", "confirmed", "shipped", "delivered", "cancelled"] = "placed"
    razorpay_order_id: Optional[str] = None
    razorpay_payment_id: Optional[str] = None
    razorpay_amount_paise: Optional[int] = None
    created_at: str


class ChatReq(BaseModel):
    message: str
    session_id: Optional[str] = None


class BidReq(BaseModel):
    amount: float


class PaymentVerifyReq(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str


class RefundReq(BaseModel):
    amount: Optional[float] = None  # full refund when None
    reason: Optional[str] = None


# ------------------ Helpers ------------------
def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def hash_pw(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()


def verify_pw(pw: str, hashed: str) -> bool:
    return bcrypt.checkpw(pw.encode(), hashed.encode())


def make_jwt(user_id: str) -> str:
    payload: dict = {"user_id": user_id, "exp": datetime.now(timezone.utc) + timedelta(days=7)}
    return pyjwt.encode(payload, JWT_SECRET, algorithm="HS256")


def public_user(doc: dict) -> dict:
    """Strip private fields (password, _id) from a user document."""
    return {k: v for k, v in doc.items() if k not in ("password", "_id")}


def get_client_ip(request: Request) -> str:
    """Honour X-Forwarded-For when behind a reverse proxy / ingress."""
    fwd = request.headers.get("X-Forwarded-For", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# ------------------ Brute-force lockout helpers ------------------
async def _ensure_aware(dt) -> datetime:
    if isinstance(dt, str):
        dt = datetime.fromisoformat(dt)
    if not dt.tzinfo:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


async def check_lockout(identifier: str) -> None:
    rec = await db.login_attempts.find_one({"identifier": identifier})
    if not rec or not rec.get("locked_until"):
        return
    locked_until = await _ensure_aware(rec["locked_until"])
    now = datetime.now(timezone.utc)
    if locked_until > now:
        retry_after = int((locked_until - now).total_seconds())
        minutes = retry_after // 60 + 1
        raise HTTPException(
            status_code=429,
            detail=f"Too many failed attempts. Account locked. Try again in {minutes} minute(s).",
            headers={"Retry-After": str(retry_after)},
        )


async def record_failed_login(identifier: str) -> int:
    now = datetime.now(timezone.utc)
    rec = await db.login_attempts.find_one({"identifier": identifier}) or {}
    attempts = int(rec.get("attempts", 0)) + 1
    update = {"identifier": identifier, "attempts": attempts, "last_attempt_at": now}
    if attempts >= LOCK_THRESHOLD:
        update["locked_until"] = now + LOCK_DURATION
    await db.login_attempts.update_one({"identifier": identifier}, {"$set": update}, upsert=True)
    return attempts


async def clear_attempts(identifier: str) -> None:
    await db.login_attempts.delete_one({"identifier": identifier})


async def clear_attempts_for_email(email: str) -> None:
    await db.login_attempts.delete_many({"identifier": {"$regex": f":{email.lower()}$"}})


def _user_id_from_jwt(token: str) -> Optional[str]:
    try:
        payload = pyjwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        return payload.get("user_id")
    except Exception:
        return None


async def _user_id_from_session(token: str) -> Optional[str]:
    sess = await db.user_sessions.find_one({"session_token": token}, {"_id": 0})
    if not sess:
        return None
    expires_at = sess["expires_at"]
    if isinstance(expires_at, str):
        expires_at = datetime.fromisoformat(expires_at)
    if not expires_at.tzinfo:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < datetime.now(timezone.utc):
        return None
    return sess["user_id"]


async def get_current_user(
    request: Request,
    kb_token: Optional[str] = Cookie(None),
    session_token: Optional[str] = Cookie(None),
) -> User:
    """Resolve the current user. Priority: httpOnly JWT cookie → Google session cookie → Authorization Bearer (legacy)."""
    user_id: Optional[str] = None

    if kb_token:
        user_id = _user_id_from_jwt(kb_token)

    if not user_id and session_token:
        user_id = await _user_id_from_session(session_token)

    if not user_id:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            bearer = auth.split(" ", 1)[1]
            user_id = _user_id_from_jwt(bearer)
            if not user_id:
                user_id = await _user_id_from_session(bearer)

    if not user_id:
        raise HTTPException(401, "Not authenticated")

    user_doc = await db.users.find_one({"user_id": user_id}, {"_id": 0, "password": 0})
    if not user_doc:
        raise HTTPException(401, "User not found")
    return User(**user_doc)


async def optional_user(
    request: Request,
    kb_token: Optional[str] = Cookie(None),
    session_token: Optional[str] = Cookie(None),
) -> Optional[User]:
    try:
        return await get_current_user(request, kb_token=kb_token, session_token=session_token)
    except HTTPException:
        return None


# ------------------ CSRF middleware ------------------
@app.middleware("http")
async def csrf_middleware(request: Request, call_next):
    """Double-submit CSRF: header must equal cookie on state-changing requests when authenticated."""
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        path = request.url.path
        if path not in CSRF_EXEMPT_PATHS and path.startswith("/api/"):
            has_auth_cookie = request.cookies.get(AUTH_COOKIE) or request.cookies.get(SESSION_COOKIE)
            if has_auth_cookie:
                csrf_cookie = request.cookies.get(CSRF_COOKIE)
                csrf_header = request.headers.get(CSRF_HEADER)
                if not csrf_cookie or not csrf_header or not secrets.compare_digest(csrf_cookie, csrf_header):
                    return JSONResponse(status_code=403, content={"detail": "CSRF token missing or invalid"})
    return await call_next(request)


# ------------------ Auth Routes ------------------
@api.post("/auth/register")
async def register(req: RegisterReq, response: Response):
    email = req.email.lower()
    existing = await db.users.find_one({"email": email}, {"_id": 0})
    if existing:
        raise HTTPException(400, "Email already registered")
    user_id = f"user_{uuid.uuid4().hex[:12]}"
    doc = {
        "user_id": user_id,
        "email": email,
        "password": hash_pw(req.password),
        "name": req.name,
        "role": req.role,
        "phone": req.phone,
        "location": req.location,
        "picture": None,
        "verified": False,
        "created_at": now_iso(),
    }
    await db.users.insert_one(doc)
    token = make_jwt(user_id)
    csrf = _set_auth_cookies(response, token)
    return {"user": public_user(doc), "csrf_token": csrf}


@api.post("/auth/login")
async def login(req: LoginReq, request: Request, response: Response):
    email = req.email.lower()
    identifier = f"{get_client_ip(request)}:{email}"
    await check_lockout(identifier)

    user = await db.users.find_one({"email": email}, {"_id": 0})
    valid = bool(user and "password" in user and verify_pw(req.password, user["password"]))
    if not valid:
        attempts = await record_failed_login(identifier)
        remaining = max(0, LOCK_THRESHOLD - attempts)
        if remaining == 0:
            raise HTTPException(
                status_code=429,
                detail="Too many failed attempts. Account locked for 15 minutes.",
                headers={"Retry-After": str(int(LOCK_DURATION.total_seconds()))},
            )
        if remaining <= 2:
            raise HTTPException(401, f"Invalid credentials ({remaining} attempt{'s' if remaining != 1 else ''} remaining)")
        raise HTTPException(401, "Invalid credentials")

    await clear_attempts(identifier)
    token = make_jwt(user["user_id"])
    csrf = _set_auth_cookies(response, token)
    return {"user": public_user(user), "csrf_token": csrf}


@api.get("/auth/me")
async def me(response: Response, user: User = Depends(get_current_user), csrf_token: Optional[str] = Cookie(None)):
    # Ensure CSRF cookie exists for any authenticated session (covers legacy logins)
    if not csrf_token:
        new_csrf = secrets.token_urlsafe(32)
        response.set_cookie(
            CSRF_COOKIE, new_csrf,
            httponly=False, secure=True, samesite="lax", path="/", max_age=COOKIE_MAX_AGE,
        )
    return user


@api.post("/auth/csrf")
async def issue_csrf(response: Response):
    """Issue (or rotate) a CSRF token. Safe to call before login as well."""
    csrf = secrets.token_urlsafe(32)
    response.set_cookie(
        CSRF_COOKIE, csrf,
        httponly=False, secure=True, samesite="lax", path="/", max_age=COOKIE_MAX_AGE,
    )
    return {"csrf_token": csrf}


@api.post("/auth/logout")
async def logout(response: Response, session_token: Optional[str] = Cookie(None)):
    if session_token:
        await db.user_sessions.delete_one({"session_token": session_token})
    _clear_auth_cookies(response)
    return {"ok": True}


@api.post("/auth/forgot-password")
async def forgot_password(req: ForgotPasswordReq):
    """Issue a single-use reset token (1hr TTL). Always returns the same response to prevent email enumeration."""
    email = req.email.lower()
    user = await db.users.find_one({"email": email}, {"_id": 0})
    if user:
        token = secrets.token_urlsafe(32)
        expires_at = datetime.now(timezone.utc) + RESET_TOKEN_TTL
        await db.password_reset_tokens.insert_one({
            "token": token,
            "user_id": user["user_id"],
            "email": email,
            "expires_at": expires_at,
            "used": False,
            "created_at": now_iso(),
        })
        reset_link = f"{FRONTEND_URL.rstrip('/')}/reset-password?token={token}"
        # In production, email this link. For dev we log it so testing can pull from backend logs.
        logger.info("PASSWORD_RESET_LINK email=%s link=%s", email, reset_link)
    return {"ok": True, "message": "If an account exists for that email, a reset link has been sent."}


@api.post("/auth/reset-password")
async def reset_password(req: ResetPasswordReq):
    if len(req.new_password) < MIN_PW_LEN:
        raise HTTPException(400, f"Password must be at least {MIN_PW_LEN} characters")
    rec = await db.password_reset_tokens.find_one({"token": req.token})
    if not rec or rec.get("used"):
        raise HTTPException(400, "Invalid or expired reset token")
    expires_at = await _ensure_aware(rec["expires_at"])
    if expires_at < datetime.now(timezone.utc):
        raise HTTPException(400, "Invalid or expired reset token")
    await db.users.update_one(
        {"user_id": rec["user_id"]},
        {"$set": {"password": hash_pw(req.new_password)}},
    )
    await db.password_reset_tokens.update_one(
        {"token": req.token},
        {"$set": {"used": True, "used_at": now_iso()}},
    )
    # Clear any active lockouts so the user can log in immediately after reset
    await clear_attempts_for_email(rec["email"])
    return {"ok": True, "message": "Password updated. You can now log in."}


@api.post("/auth/google/session")
async def google_session(request: Request, response: Response):
    """Exchange Emergent session_id for our session_token cookie + CSRF cookie."""
    session_id = request.headers.get("X-Session-ID")
    if not session_id:
        raise HTTPException(400, "Missing session_id")
    async with httpx.AsyncClient(timeout=15) as cl:
        r = await cl.get(
            "https://demobackend.emergentagent.com/auth/v1/env/oauth/session-data",
            headers={"X-Session-ID": session_id},
        )
    if r.status_code != 200:
        raise HTTPException(401, "Invalid session")
    data = r.json()
    email = data["email"]
    name = data.get("name", email)
    picture = data.get("picture")
    session_token = data["session_token"]

    user = await db.users.find_one({"email": email}, {"_id": 0})
    if not user:
        user_id = f"user_{uuid.uuid4().hex[:12]}"
        user_doc = {
            "user_id": user_id,
            "email": email,
            "name": name,
            "picture": picture,
            "role": "buyer",
            "verified": True,
            "created_at": now_iso(),
        }
        await db.users.insert_one(user_doc)
        user = user_doc

    expires_at = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    await db.user_sessions.insert_one(
        {
            "user_id": user["user_id"],
            "session_token": session_token,
            "expires_at": expires_at,
            "created_at": now_iso(),
        }
    )
    response.set_cookie(
        SESSION_COOKIE, session_token, httponly=True, secure=True, samesite="none", path="/",
        max_age=COOKIE_MAX_AGE,
    )
    csrf = secrets.token_urlsafe(32)
    response.set_cookie(
        CSRF_COOKIE, csrf, httponly=False, secure=True, samesite="none", path="/",
        max_age=COOKIE_MAX_AGE,
    )
    return {"user": public_user(user), "csrf_token": csrf}


# ------------------ Products ------------------
CATEGORIES = [
    {"id": "vegetables", "name": "Vegetables", "icon": "Salad"},
    {"id": "fruits", "name": "Fruits", "icon": "Apple"},
    {"id": "grains", "name": "Grains", "icon": "Wheat"},
    {"id": "rice", "name": "Rice", "icon": "Wheat"},
    {"id": "pulses", "name": "Pulses", "icon": "Bean"},
    {"id": "spices", "name": "Spices", "icon": "Flame"},
    {"id": "flowers", "name": "Flowers", "icon": "Flower"},
    {"id": "medicinal", "name": "Medicinal Plants", "icon": "Leaf"},
    {"id": "organic", "name": "Organic Produce", "icon": "Sprout"},
    {"id": "dairy", "name": "Dairy", "icon": "Milk"},
    {"id": "honey", "name": "Honey", "icon": "Droplet"},
    {"id": "seeds", "name": "Seeds", "icon": "Sprout"},
    {"id": "fertilizers", "name": "Fertilizers", "icon": "FlaskConical"},
    {"id": "equipment", "name": "Equipment", "icon": "Tractor"},
    {"id": "livestock", "name": "Livestock", "icon": "Beef"},
    {"id": "fishery", "name": "Fishery", "icon": "Fish"},
    {"id": "poultry", "name": "Poultry", "icon": "Egg"},
]


@api.get("/categories")
async def categories():
    return CATEGORIES


@api.get("/products")
async def list_products(
    category: Optional[str] = None,
    q: Optional[str] = None,
    state: Optional[str] = None,
    organic: Optional[bool] = None,
    export_ready: Optional[bool] = None,
    auction: Optional[bool] = None,
    limit: int = 60,
):
    query = {}
    if category:
        query["category"] = category
    if q:
        query["$or"] = [
            {"title": {"$regex": q, "$options": "i"}},
            {"description": {"$regex": q, "$options": "i"}},
            {"farmer_name": {"$regex": q, "$options": "i"}},
            {"location": {"$regex": q, "$options": "i"}},
        ]
    if state:
        query["state"] = state
    if organic:
        query["organic"] = True
    if export_ready:
        query["export_ready"] = True
    if auction:
        query["auction"] = True
    docs = await db.products.find(query, {"_id": 0}).sort("created_at", -1).to_list(limit)
    return docs


@api.get("/products/{pid}")
async def get_product(pid: str):
    doc = await db.products.find_one({"product_id": pid}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Not found")
    return doc


@api.post("/products")
async def create_product(req: ProductCreate, user: User = Depends(get_current_user)):
    if user.role not in ("farmer", "admin"):
        raise HTTPException(403, "Only farmers can list products")
    pid = f"prod_{uuid.uuid4().hex[:10]}"
    doc = {
        "product_id": pid,
        "farmer_id": user.user_id,
        "farmer_name": user.name,
        **req.model_dump(),
        "current_bid": req.price if req.auction else None,
        "created_at": now_iso(),
    }
    await db.products.insert_one(doc)
    doc.pop("_id", None)
    return doc


@api.delete("/products/{pid}")
async def delete_product(pid: str, user: User = Depends(get_current_user)):
    prod = await db.products.find_one({"product_id": pid}, {"_id": 0})
    if not prod:
        raise HTTPException(404, "Not found")
    if prod["farmer_id"] != user.user_id and user.role != "admin":
        raise HTTPException(403, "Forbidden")
    # Cascade-delete Cloudinary assets (best-effort; failures logged)
    public_ids = [
        img.get("public_id")
        for img in (prod.get("images") or [])
        if isinstance(img, dict) and img.get("public_id")
    ]
    if public_ids:
        cloudinary_delete_many(public_ids)
    await db.products.delete_one({"product_id": pid})
    return {"ok": True}


class ProductUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    price: Optional[float] = None
    unit: Optional[str] = None
    moq: Optional[int] = None
    available_qty: Optional[int] = None
    quality_grade: Optional[Literal["A", "B", "C", "Export"]] = None
    organic: Optional[bool] = None
    export_ready: Optional[bool] = None
    images: Optional[List] = None
    location: Optional[str] = None
    state: Optional[str] = None
    harvest_date: Optional[str] = None


@api.put("/products/{pid}")
async def update_product(pid: str, req: ProductUpdate, user: User = Depends(get_current_user)):
    prod = await db.products.find_one({"product_id": pid}, {"_id": 0})
    if not prod:
        raise HTTPException(404, "Not found")
    if prod["farmer_id"] != user.user_id and user.role != "admin":
        raise HTTPException(403, "Forbidden")
    updates = {k: v for k, v in req.model_dump(exclude_unset=True).items() if v is not None}
    # If images are replaced, cascade-delete removed Cloudinary assets
    if "images" in updates:
        old_ids = {
            img.get("public_id")
            for img in (prod.get("images") or [])
            if isinstance(img, dict) and img.get("public_id")
        }
        new_ids = {
            img.get("public_id")
            for img in updates["images"]
            if isinstance(img, dict) and img.get("public_id")
        }
        orphans = old_ids - new_ids
        if orphans:
            cloudinary_delete_many(orphans)
    if updates:
        await db.products.update_one({"product_id": pid}, {"$set": updates})
    updated = await db.products.find_one({"product_id": pid}, {"_id": 0})
    return updated


# ------------------ Cloudinary signed-upload + delete ------------------
class CloudinaryDeleteReq(BaseModel):
    public_id: str


@api.get("/cloudinary/signature")
async def cloudinary_signature(
    folder: Optional[str] = None,
    user: User = Depends(get_current_user),
):
    """Return signed params so the SPA can upload directly to Cloudinary.
    Assets are scoped to `kisanbaazar/products/<user_id>/` so the uploader can
    later remove pre-submit (orphan) assets without needing a referencing product row.
    """
    if not CLOUDINARY_ENABLED:
        raise HTTPException(503, "Image upload not configured")
    try:
        payload = cloudinary_signature_payload(folder, user_id=user.user_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return payload


@api.delete("/cloudinary/image")
async def cloudinary_delete(
    req: CloudinaryDeleteReq,
    user: User = Depends(get_current_user),
):
    """Delete a Cloudinary asset. Allowed if (a) caller is admin, (b) the asset
    lives in the caller's signed-upload subfolder, or (c) the asset is currently
    attached to a product the caller owns.
    """
    if not CLOUDINARY_ENABLED:
        raise HTTPException(503, "Image upload not configured")
    pid = req.public_id.strip()
    if not pid:
        raise HTTPException(400, "public_id required")

    if user.role != "admin" and not cloudinary_user_owns(pid, user.user_id):
        owning_product = await db.products.find_one(
            {"farmer_id": user.user_id, "images.public_id": pid},
            {"_id": 0, "product_id": 1},
        )
        if not owning_product:
            raise HTTPException(403, "Forbidden")

    ok = cloudinary_delete_image(pid)
    if not ok:
        raise HTTPException(502, "Cloudinary delete failed")
    # Detach from any product references that still hold it
    await db.products.update_many(
        {"images.public_id": pid},
        {"$pull": {"images": {"public_id": pid}}},
    )
    return {"ok": True, "public_id": pid}


@api.post("/products/{pid}/bid")
async def bid(pid: str, req: BidReq, user: User = Depends(get_current_user)):
    prod = await db.products.find_one({"product_id": pid}, {"_id": 0})
    if not prod:
        raise HTTPException(404, "Not found")
    if not prod.get("auction"):
        raise HTTPException(400, "Not an auction")
    if req.amount <= (prod.get("current_bid") or 0):
        raise HTTPException(400, "Bid must be higher than current bid")
    await db.products.update_one(
        {"product_id": pid},
        {"$set": {"current_bid": req.amount, "current_bidder": user.user_id, "current_bidder_name": user.name}},
    )
    await db.bids.insert_one(
        {"product_id": pid, "user_id": user.user_id, "amount": req.amount, "created_at": now_iso()}
    )
    return {"current_bid": req.amount}


# ------------------ Orders ------------------
@api.post("/orders")
async def create_order(req: OrderCreate, user: User = Depends(get_current_user)):
    subtotal = sum(it.qty * it.price for it in req.items)
    # Front-end fee: 1% rounded — same calc as Checkout summary.
    charge_total = round(subtotal * 1.01)
    oid = f"ord_{uuid.uuid4().hex[:10]}"

    rzp_id: Optional[str] = None
    rzp_amount_paise = int(round(charge_total * 100))
    # COD never hits the payment gateway. Other methods use Razorpay when
    # configured; otherwise we fall back to the MOCK id (dev environments).
    if req.payment_method != "cod":
        if razorpay_enabled():
            try:
                rzp = razorpay_create_order(
                    rzp_amount_paise,
                    receipt=oid,
                    notes={"buyer_id": user.user_id, "method": req.payment_method},
                )
                rzp_id = rzp["id"]
            except Exception:
                logger.exception("Razorpay order creation failed; falling back to mock id")
                rzp_id = f"order_mock_{uuid.uuid4().hex[:14]}"
        else:
            rzp_id = f"order_mock_{uuid.uuid4().hex[:14]}"

    doc = {
        "order_id": oid,
        "buyer_id": user.user_id,
        "buyer_name": user.name,
        "items": [it.model_dump() for it in req.items],
        "total": subtotal,
        "charge_total": charge_total,
        "delivery_address": req.delivery_address,
        "payment_method": req.payment_method,
        "payment_status": "pending",
        "status": "placed",
        "razorpay_order_id": rzp_id,
        "razorpay_amount_paise": rzp_amount_paise if req.payment_method != "cod" else 0,
        "created_at": now_iso(),
    }
    await db.orders.insert_one(doc)
    doc.pop("_id", None)
    return doc


@api.get("/payments/config")
async def payments_config():
    """Public payment config so the frontend knows whether to use real
    Razorpay checkout (`enabled=true` + `key_id`) or the MOCK fallback."""
    return razorpay_public_config()


@api.post("/orders/{oid}/verify")
async def verify_payment(oid: str, req: PaymentVerifyReq, user: User = Depends(get_current_user)):
    """Verify Razorpay's checkout-success signature and mark order paid.
    The post-payment workflow (stock decrement, payments row, notifications)
    is delegated to `payments_service.finalise_paid_order()` which is
    idempotent."""
    order = await db.orders.find_one({"order_id": oid}, {"_id": 0})
    if not order:
        raise HTTPException(404, "Not found")
    if order["buyer_id"] != user.user_id:
        raise HTTPException(403, "Forbidden")
    if order.get("razorpay_order_id") != req.razorpay_order_id:
        raise HTTPException(400, "Order id mismatch")
    if not razorpay_verify_signature(
        req.razorpay_order_id, req.razorpay_payment_id, req.razorpay_signature
    ):
        await mark_payment_failed(
            db, order=order, razorpay_payment_id=req.razorpay_payment_id,
            reason="signature_mismatch",
        )
        raise HTTPException(400, "Invalid payment signature")
    await finalise_paid_order(
        db,
        order=order,
        razorpay_payment_id=req.razorpay_payment_id,
        razorpay_signature=req.razorpay_signature,
        amount_paise=int(order.get("razorpay_amount_paise") or 0),
        source="verify",
    )
    return {"ok": True, "payment_id": req.razorpay_payment_id}


@api.post("/orders/{oid}/pay")
async def mock_pay(oid: str, user: User = Depends(get_current_user)):
    """MOCK payment finaliser — only allowed when real Razorpay is not
    configured (dev fallback) or when payment_method == 'cod'."""
    order = await db.orders.find_one({"order_id": oid}, {"_id": 0})
    if not order:
        raise HTTPException(404, "Not found")
    if order["buyer_id"] != user.user_id:
        raise HTTPException(403, "Forbidden")
    is_cod = order.get("payment_method") == "cod"
    if razorpay_enabled() and not is_cod:
        raise HTTPException(400, "Real Razorpay is enabled — use /verify instead")
    payment_id = f"pay_mock_{uuid.uuid4().hex[:14]}"
    if is_cod:
        # COD: do not consider it captured yet — but reserve stock + notify.
        await finalise_paid_order(
            db, order=order, razorpay_payment_id=payment_id,
            razorpay_signature=None,
            amount_paise=int(order.get("razorpay_amount_paise") or 0),
            source="mock", method="cod",
        )
        # Override: COD orders stay payment_status=pending until delivered.
        await db.orders.update_one(
            {"order_id": oid},
            {"$set": {"payment_status": "pending", "status": "placed"}},
        )
        await db.payments.update_one(
            {"razorpay_payment_id": payment_id},
            {"$set": {"status": "cod_pending"}},
        )
    else:
        await finalise_paid_order(
            db, order=order, razorpay_payment_id=payment_id,
            razorpay_signature=None,
            amount_paise=int(order.get("razorpay_amount_paise") or 0),
            source="mock",
        )
    return {"ok": True, "payment_id": payment_id}


@api.post("/payments/webhook")
async def razorpay_webhook(request: Request):
    """Razorpay async event webhook. HMAC-verified, idempotent on payment_id.
    Handles payment.captured / payment.authorized / payment.failed / refund.processed."""
    raw = await request.body()
    sig = request.headers.get("X-Razorpay-Signature", "")
    if not razorpay_verify_webhook(raw, sig):
        raise HTTPException(400, "Invalid webhook signature")
    payload: dict = {}
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid payload")
    event = payload.get("event", "")
    payload_body = payload.get("payload", {})

    # ---- refund.processed ----
    if event.startswith("refund."):
        refund_entity = payload_body.get("refund", {}).get("entity", {})
        rzp_payment_id = refund_entity.get("payment_id")
        refund_id = refund_entity.get("id")
        amount_paise = int(refund_entity.get("amount") or 0)
        status = refund_entity.get("status") or event.split(".", 1)[-1]
        if rzp_payment_id and refund_id:
            await record_refund(
                db, razorpay_payment_id=rzp_payment_id, refund_id=refund_id,
                amount_paise=amount_paise, status=status,
            )
        return {"ok": True, "event": event}

    # ---- payment.* ----
    payment_entity = payload_body.get("payment", {}).get("entity", {})
    rzp_order_id = payment_entity.get("order_id")
    rzp_payment_id = payment_entity.get("id")
    amount_paise = int(payment_entity.get("amount") or 0)
    method = payment_entity.get("method")
    if not rzp_order_id:
        return {"ok": True, "skipped": True}
    order = await db.orders.find_one({"razorpay_order_id": rzp_order_id}, {"_id": 0})
    if not order:
        logger.warning("Webhook %s for unknown rzp_order_id=%s", event, rzp_order_id)
        return {"ok": True, "skipped": True}

    if event in ("payment.captured", "payment.authorized"):
        await finalise_paid_order(
            db, order=order,
            razorpay_payment_id=rzp_payment_id,
            razorpay_signature=None,
            amount_paise=amount_paise or int(order.get("razorpay_amount_paise") or 0),
            source="webhook",
            method=method,
        )
    elif event == "payment.failed":
        await mark_payment_failed(
            db, order=order, razorpay_payment_id=rzp_payment_id,
            reason=(payment_entity.get("error_description") or "razorpay_failed"),
        )
    logger.info("Razorpay webhook %s applied to %s", event, rzp_order_id)
    return {"ok": True, "event": event}


# ------------------ Payment views (history, refund, invoice) ------------------
@api.get("/payments")
async def list_my_payments(user: User = Depends(get_current_user)):
    """Buyer's payment history (own only). Admin sees all."""
    query = {} if user.role == "admin" else {"user_id": user.user_id}
    docs = await db.payments.find(query, {"_id": 0}).sort("created_at", -1).to_list(500)
    return docs


@api.get("/admin/payments")
async def admin_list_payments(
    status: Optional[str] = None,
    user: User = Depends(get_current_user),
):
    if user.role != "admin":
        raise HTTPException(403, "Admin only")
    q: dict = {}
    if status:
        q["status"] = status
    docs = await db.payments.find(q, {"_id": 0}).sort("created_at", -1).to_list(1000)
    return docs


@api.get("/farmer/payments")
async def farmer_received_payments(user: User = Depends(get_current_user)):
    """List payments containing this farmer's products. Adds settlement_status."""
    if user.role not in ("farmer", "admin"):
        raise HTTPException(403, "Farmer only")
    my_pids = [
        p["product_id"]
        async for p in db.products.find(
            {"farmer_id": user.user_id}, {"_id": 0, "product_id": 1}
        )
    ]
    if not my_pids:
        return []
    my_orders = await db.orders.find(
        {"items.product_id": {"$in": my_pids}, "payment_status": {"$in": ["paid", "refunded"]}},
        {"_id": 0, "order_id": 1, "items": 1, "buyer_name": 1},
    ).to_list(1000)
    oid_to_order = {o["order_id"]: o for o in my_orders}
    payments = await db.payments.find(
        {"order_id": {"$in": list(oid_to_order.keys())}, "status": {"$in": ["captured", "refunded"]}},
        {"_id": 0},
    ).sort("created_at", -1).to_list(1000)
    # Per-payment: only include the portion that belongs to this farmer.
    out: list = []
    for pmt in payments:
        order = oid_to_order.get(pmt["order_id"])
        if not order:
            continue
        farmer_amount = sum(
            (it.get("qty") or 0) * (it.get("price") or 0)
            for it in order.get("items", [])
            if it.get("product_id") in my_pids
        )
        out.append({
            **pmt,
            "farmer_amount": farmer_amount,
            "buyer_name": order.get("buyer_name"),
        })
    return out


@api.post("/admin/payments/{rzp_payment_id}/refund")
async def admin_refund(
    rzp_payment_id: str, req: RefundReq,
    user: User = Depends(get_current_user),
):
    if user.role != "admin":
        raise HTTPException(403, "Admin only")
    if not razorpay_enabled():
        raise HTTPException(400, "Razorpay not configured")
    pmt = await db.payments.find_one({"razorpay_payment_id": rzp_payment_id}, {"_id": 0})
    if not pmt:
        raise HTTPException(404, "Payment not found")
    if pmt.get("status") != "captured":
        raise HTTPException(400, f"Cannot refund a payment with status={pmt.get('status')}")
    amount_paise: Optional[int] = None
    if req.amount is not None:
        amount_paise = int(round(req.amount * 100))
        if amount_paise <= 0 or amount_paise > int(pmt.get("amount_paise") or 0):
            raise HTTPException(400, "Invalid refund amount")
    try:
        refund = razorpay_refund_payment(
            rzp_payment_id, amount_paise=amount_paise,
            notes={"reason": req.reason or "admin_refund", "admin_id": user.user_id},
        )
        await record_refund(
            db,
            razorpay_payment_id=rzp_payment_id,
            refund_id=refund["id"],
            amount_paise=int(refund.get("amount") or amount_paise or pmt["amount_paise"]),
            status=refund.get("status", "processed"),
        )
        return {"ok": True, "refund_id": refund["id"], "status": refund.get("status")}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Razorpay refund failed")
        raise HTTPException(502, f"Refund failed: {e}")


@api.get("/orders/{oid}/invoice")
async def download_invoice(oid: str, user: User = Depends(get_current_user)):
    """Streaming PDF invoice. Buyer or admin only. Only generated for paid orders."""
    order = await db.orders.find_one({"order_id": oid}, {"_id": 0})
    if not order:
        raise HTTPException(404, "Not found")
    if user.role != "admin" and order["buyer_id"] != user.user_id:
        raise HTTPException(403, "Forbidden")
    if order.get("payment_status") not in ("paid", "refunded"):
        raise HTTPException(400, "Invoice only available after payment")
    payment = await db.payments.find_one({"order_id": oid}, {"_id": 0})
    pdf = generate_invoice_pdf(order, payment)
    return Response(
        content=pdf, media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="invoice_{oid}.pdf"'},
    )


@api.post("/orders/{oid}/retry-payment")
async def retry_payment(oid: str, user: User = Depends(get_current_user)):
    """Re-create a fresh Razorpay order for a previously failed order. Returns
    the new razorpay_order_id so the frontend can re-open the checkout modal."""
    order = await db.orders.find_one({"order_id": oid}, {"_id": 0})
    if not order:
        raise HTTPException(404, "Not found")
    if order["buyer_id"] != user.user_id:
        raise HTTPException(403, "Forbidden")
    if order.get("payment_status") == "paid":
        raise HTTPException(400, "Already paid")
    if order.get("payment_method") == "cod":
        raise HTTPException(400, "COD orders cannot be retried via gateway")
    amount_paise = int(order.get("razorpay_amount_paise") or 0)
    if amount_paise < 100:
        raise HTTPException(400, "Invalid order amount")
    if razorpay_enabled():
        try:
            rzp = razorpay_create_order(
                amount_paise, receipt=oid,
                notes={"buyer_id": user.user_id, "retry_for": oid},
            )
            new_id = rzp["id"]
        except Exception as e:
            logger.exception("retry-payment: gateway error")
            raise HTTPException(502, f"Gateway error: {e}")
    else:
        new_id = f"order_mock_{uuid.uuid4().hex[:14]}"
    await db.orders.update_one(
        {"order_id": oid},
        {"$set": {"razorpay_order_id": new_id, "payment_status": "pending"}},
    )
    return {"order_id": oid, "razorpay_order_id": new_id, "razorpay_amount_paise": amount_paise}


# ------------------ Notifications ------------------
@api.get("/notifications")
async def list_notifications(user: User = Depends(get_current_user)):
    docs = await db.notifications.find(
        {"user_id": user.user_id}, {"_id": 0}
    ).sort("created_at", -1).limit(100).to_list(100)
    unread = sum(1 for n in docs if not n.get("read"))
    return {"items": docs, "unread": unread}


@api.post("/notifications/{nid}/read")
async def mark_notification_read(nid: str, user: User = Depends(get_current_user)):
    r = await db.notifications.update_one(
        {"notification_id": nid, "user_id": user.user_id},
        {"$set": {"read": True}},
    )
    if r.matched_count == 0:
        raise HTTPException(404, "Not found")
    return {"ok": True}


@api.post("/notifications/read-all")
async def mark_all_read(user: User = Depends(get_current_user)):
    await db.notifications.update_many(
        {"user_id": user.user_id, "read": False}, {"$set": {"read": True}}
    )
    return {"ok": True}


@api.get("/orders")
async def list_orders(user: User = Depends(get_current_user)):
    docs: list = []
    if user.role == "admin":
        docs = await db.orders.find({}, {"_id": 0}).sort("created_at", -1).to_list(500)
    elif user.role == "farmer":
        prods = await db.products.find({"farmer_id": user.user_id}, {"_id": 0, "product_id": 1}).to_list(500)
        pids = [p["product_id"] for p in prods]
        docs = await db.orders.find({"items.product_id": {"$in": pids}}, {"_id": 0}).sort("created_at", -1).to_list(500)
    else:
        docs = await db.orders.find({"buyer_id": user.user_id}, {"_id": 0}).sort("created_at", -1).to_list(500)
    return docs


# ------------------ Dashboard Stats ------------------
@api.get("/dashboard/stats")
async def stats(user: User = Depends(get_current_user)):
    if user.role == "farmer":
        prods = await db.products.count_documents({"farmer_id": user.user_id})
        my_prod_ids = [p["product_id"] async for p in db.products.find({"farmer_id": user.user_id}, {"_id": 0, "product_id": 1})]
        orders_cur = db.orders.find({"items.product_id": {"$in": my_prod_ids}}, {"_id": 0})
        revenue = 0.0
        order_count = 0
        async for o in orders_cur:
            order_count += 1
            for it in o["items"]:
                if it["product_id"] in my_prod_ids:
                    revenue += it["qty"] * it["price"]
        return {"products": prods, "orders": order_count, "revenue": revenue}
    if user.role == "admin":
        return {
            "users": await db.users.count_documents({}),
            "products": await db.products.count_documents({}),
            "orders": await db.orders.count_documents({}),
            "revenue": sum([o["total"] async for o in db.orders.find({"payment_status": "paid"}, {"_id": 0, "total": 1})]),
        }
    orders = await db.orders.count_documents({"buyer_id": user.user_id})
    wishlist = await db.wishlist.count_documents({"user_id": user.user_id})
    return {"orders": orders, "wishlist": wishlist}


# ------------------ Wishlist ------------------
@api.post("/wishlist/{pid}")
async def add_wishlist(pid: str, user: User = Depends(get_current_user)):
    await db.wishlist.update_one(
        {"user_id": user.user_id, "product_id": pid},
        {"$set": {"user_id": user.user_id, "product_id": pid, "created_at": now_iso()}},
        upsert=True,
    )
    return {"ok": True}


@api.delete("/wishlist/{pid}")
async def remove_wishlist(pid: str, user: User = Depends(get_current_user)):
    await db.wishlist.delete_one({"user_id": user.user_id, "product_id": pid})
    return {"ok": True}


@api.get("/wishlist")
async def get_wishlist(user: User = Depends(get_current_user)):
    items = await db.wishlist.find({"user_id": user.user_id}, {"_id": 0}).to_list(200)
    pids = [i["product_id"] for i in items]
    products = await db.products.find({"product_id": {"$in": pids}}, {"_id": 0}).to_list(200)
    return products


# ------------------ AI Chat (Claude Sonnet 4.5) ------------------
SYSTEM_PROMPT = """You are KisanBaazar AI, a helpful assistant for an Indian agriculture marketplace.
You help farmers price their crops, recommend crops by season/region, detect fraud red-flags in listings,
give negotiation tips between buyers and farmers, and answer questions about organic certification,
export procedures, government schemes (PM-KISAN, e-NAM, MSP), and market trends.
Be concise, friendly, and culturally aware. Provide practical Indian context (INR pricing, mandis,
state-specific advice). Keep replies under 200 words unless asked for detail."""


@api.post("/ai/chat")
async def ai_chat(req: ChatReq, user: Optional[User] = Depends(optional_user)):
    sid = req.session_id or f"sess_{uuid.uuid4().hex[:10]}"

    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=sid,
        system_message=SYSTEM_PROMPT,
    ).with_model("anthropic", "claude-sonnet-4-5-20250929")

    async def gen():
        full = ""
        try:
            async for ev in chat.stream_message(UserMessage(text=req.message)):
                if isinstance(ev, TextDelta):
                    full += ev.content
                    yield ev.content
                elif isinstance(ev, StreamDone):
                    break
        except Exception as e:
            logger.exception("AI error")
            yield f"\n[error: {e}]"
        await db.chat_messages.insert_one(
            {
                "session_id": sid,
                "user_id": user.user_id if user else None,
                "user_msg": req.message,
                "ai_msg": full,
                "created_at": now_iso(),
            }
        )

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "X-Session-Id": sid},
    )


@api.post("/ai/price-predict")
async def price_predict(req: ChatReq, user: Optional[User] = Depends(optional_user)):
    sid = f"pp_{uuid.uuid4().hex[:8]}"
    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=sid,
        system_message="You are an Indian crop price prediction expert. Given a crop, region and season, "
                       "estimate a fair INR/kg or INR/quintal price range with brief 2-line reasoning. "
                       "Return: 'Suggested: ₹X-Y per <unit>. Why: ...'",
    ).with_model("anthropic", "claude-sonnet-4-5-20250929")
    full = ""
    try:
        async for ev in chat.stream_message(UserMessage(text=req.message)):
            if isinstance(ev, TextDelta):
                full += ev.content
            elif isinstance(ev, StreamDone):
                break
    except Exception as e:
        logger.exception("price-predict failed")
        return {"prediction": f"Suggested: market range varies. Please check local mandi rates. (AI temporarily unavailable: {type(e).__name__})"}
    return {"prediction": full or "No prediction available."}


# ------------------ Health ------------------
@api.get("/")
async def root():
    return {"message": "KisanBaazar API", "status": "ok"}


app.include_router(api)

# CORS — must use explicit origin when allow_credentials is True
_cors_origins_env = os.environ.get("CORS_ORIGINS", "")
_cors_origins = [o.strip() for o in _cors_origins_env.split(",") if o.strip() and o.strip() != "*"]
if FRONTEND_URL and FRONTEND_URL != "*" and FRONTEND_URL not in _cors_origins:
    _cors_origins.append(FRONTEND_URL)
# Fallback: if no explicit origin configured, do NOT enable credentials with wildcard
if _cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_credentials=True,
        allow_origins=_cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Session-Id"],
    )
else:
    app.add_middleware(
        CORSMiddleware,
        allow_credentials=False,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )


@app.on_event("shutdown")
async def shutdown():
    client.close()


@app.on_event("startup")
async def startup_indexes():
    """Ensure MongoDB indexes for auth security."""
    try:
        await db.password_reset_tokens.create_index("expires_at", expireAfterSeconds=0)
        await db.password_reset_tokens.create_index("token", unique=True)
        await db.login_attempts.create_index("identifier", unique=True)
        # users.email index is best-effort (existing seed data may differ in case)
        try:
            await db.users.create_index("email", unique=True)
        except Exception as e:
            logger.warning("users.email unique index skipped: %s", e)
        await ensure_payment_indexes(db)
    except Exception as e:
        logger.exception("Index creation failed: %s", e)
