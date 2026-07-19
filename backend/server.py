"""KisanBaazar - Agriculture Marketplace Backend."""
from fastapi import FastAPI, APIRouter, HTTPException, Depends, Request, Response, Cookie
from fastapi.responses import StreamingResponse, JSONResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import re
import logging
import uuid
import secrets
import bcrypt
import jwt as pyjwt
import httpx
from pathlib import Path
from pydantic import BaseModel, EmailStr, ConfigDict, field_validator
from typing import List, Optional, Literal
from datetime import datetime, timezone, timedelta


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
from reviews_service import (  # noqa: E402
    ensure_indexes as ensure_review_indexes,
    create_review as svc_create_review,
    update_review as svc_update_review,
    reply_to_review as svc_reply_review,
    report_review as svc_report_review,
    moderate_review as svc_moderate_review,
    buyer_can_review,
)
from ai_service import stream_reply as ai_stream_reply, one_shot as ai_one_shot  # noqa: E402
from email_service import send_email as send_email  # noqa: E402
import otp_service  # noqa: E402

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]
JWT_SECRET = os.environ["JWT_SECRET"]
# AI key optional at boot — endpoints degrade gracefully if unset.
EMERGENT_LLM_KEY = os.environ.get("EMERGENT_LLM_KEY", "")
FRONTEND_URL = os.environ.get("FRONTEND_URL", "*")
# Set this to ".kisanbaazar.in" once the backend is served from a
# kisanbaazar.in subdomain (e.g. api.kisanbaazar.in). This makes the auth
# cookie first-party (shared registrable domain with the frontend), which is
# what actually stops browsers from blocking it as a third-party cookie.
# Leave unset while the backend is still on *.onrender.com.
COOKIE_DOMAIN = os.environ.get("COOKIE_DOMAIN") or None

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
    "/api/auth/register/init",
    "/api/auth/register/resend-otp",
    "/api/auth/register/verify-otp",
    "/api/auth/google/session",
    "/api/auth/csrf",
    "/api/auth/forgot-password",
    "/api/auth/reset-password",
    "/api/payments/webhook",
}

# ------------------ Brute-force / Password reset constants ------------------
LOCK_THRESHOLD = 5
LOCK_DURATION = timedelta(minutes=15)
RESET_TOKEN_TTL = timedelta(minutes=15)
MIN_PW_LEN = 8
PASSWORD_HISTORY_LIMIT = 5
RESET_REQUEST_LIMIT = 3
RESET_REQUEST_WINDOW = timedelta(hours=1)


def _set_auth_cookies(response: Response, jwt_token: str, csrf_value: Optional[str] = None) -> str:
    """Set httpOnly JWT cookie + readable CSRF cookie. Returns the CSRF value used.

    samesite="none" (with secure=True) is required here because the frontend
    (kisanbaazar.in) and backend (kisanbaazar.onrender.com) are different
    sites — a "lax" cookie is never attached to cross-site XHR/fetch calls,
    only to top-level navigations, which silently 401s every API call made
    from frontend JS.
    """
    csrf_value = csrf_value or secrets.token_urlsafe(32)
    response.set_cookie(
        AUTH_COOKIE, jwt_token,
        httponly=True, secure=True, samesite="none", path="/", max_age=COOKIE_MAX_AGE,
        domain=COOKIE_DOMAIN,
    )
    response.set_cookie(
        CSRF_COOKIE, csrf_value,
        httponly=False, secure=True, samesite="none", path="/", max_age=COOKIE_MAX_AGE,
        domain=COOKIE_DOMAIN,
    )
    return csrf_value


def _clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(AUTH_COOKIE, path="/", secure=True, samesite="none", domain=COOKIE_DOMAIN)
    response.delete_cookie(CSRF_COOKIE, path="/", secure=True, samesite="none", domain=COOKIE_DOMAIN)
    response.delete_cookie(SESSION_COOKIE, path="/", secure=True, samesite="none", domain=COOKIE_DOMAIN)


# ------------------ Models ------------------
DeliveryMethod = Literal["pickup", "local_delivery", "courier", "transport", "seller_delivery"]
VehicleType = Literal["mini_truck", "tempo", "truck"]


def is_admin_role(role: str) -> bool:
    """super_admin inherits every regular-admin permission."""
    return role in ("admin", "super_admin")


def require_super_admin(user) -> None:
    if user.role != "super_admin":
        raise HTTPException(403, "Super Admin only")


class User(BaseModel):
    model_config = ConfigDict(extra="ignore")
    user_id: str
    email: str
    name: str
    role: Literal["farmer", "buyer", "exporter", "admin", "delivery_partner", "super_admin"] = "buyer"
    phone: Optional[str] = None
    location: Optional[str] = None
    picture: Optional[str] = None
    verified: bool = False
    banned: bool = False
    pw_version: int = 0
    created_at: str


# ---------- Bilingual (Marathi/English) validation error messages ----------
# Format: "English message | मराठी संदेश" so the frontend can split on '|' and
# render both, or use a lang toggle. Keeps validation contract simple.
ERR = {
    "name_len": "Name must be 2 to 50 characters | नाव 2 ते 50 अक्षरांचे असणे आवश्यक आहे",
    "name_chars": "Name may only contain letters, spaces, and dots | नावात फक्त अक्षरे, स्पेस आणि पूर्णविराम असू शकतात",
    "mobile_format": "Enter a valid 10-digit Indian mobile number starting with 6-9 | 6-9 ने सुरू होणारा वैध 10-अंकी भारतीय मोबाइल नंबर टाका",
    "pwd_short": "Password must be at least 8 characters | पासवर्ड किमान 8 अक्षरांचा असावा",
    "pwd_upper": "Password must include an uppercase letter | पासवर्डमध्ये किमान एक कॅपिटल अक्षर असावे",
    "pwd_lower": "Password must include a lowercase letter | पासवर्डमध्ये किमान एक लोअरकेस अक्षर असावे",
    "pwd_digit": "Password must include a digit | पासवर्डमध्ये किमान एक अंक असावा",
    "pwd_symbol": "Password must include a symbol (e.g., @#$!) | पासवर्डमध्ये किमान एक चिन्ह (उदा. @#$!) असावे",
    "pwd_mismatch": "Passwords do not match | पासवर्ड जुळत नाहीत",
    "email_taken": "This email is already registered | हा ईमेल आधीच नोंदणीकृत आहे",
    "mobile_taken": "This mobile number is already registered | हा मोबाइल नंबर आधीच नोंदणीकृत आहे",
    "otp_invalid": "Invalid OTP | अवैध OTP",
    "otp_expired": "OTP has expired. Please request a new one | OTP ची मुदत संपली आहे. कृपया नवीन मागवा",
    "otp_max": "Too many attempts. Please start again | खूप जास्त प्रयत्न. कृपया पुन्हा सुरू करा",
    "otp_cooldown": "Please wait {s}s before requesting another OTP | दुसरा OTP मागण्यापूर्वी कृपया {s} सेकंद थांबा",
    "session_gone": "Session expired. Please start over | सेशन संपले. कृपया पुन्हा सुरू करा",
}

MOBILE_INDIA_RE = re.compile(r"^[6-9]\d{9}$")
NAME_RE = re.compile(r"^[A-Za-z\u0900-\u097F .]+$")  # Latin + Devanagari + space/dot
_SYMBOLS_RE = re.compile(r"[^A-Za-z0-9]")


def _validate_password(pw: str) -> None:
    if len(pw) < 8:
        raise ValueError(ERR["pwd_short"])
    if not any(c.isupper() for c in pw):
        raise ValueError(ERR["pwd_upper"])
    if not any(c.islower() for c in pw):
        raise ValueError(ERR["pwd_lower"])
    if not any(c.isdigit() for c in pw):
        raise ValueError(ERR["pwd_digit"])
    if not _SYMBOLS_RE.search(pw):
        raise ValueError(ERR["pwd_symbol"])


class RegisterInitReq(BaseModel):
    email: EmailStr
    password: str
    confirm_password: str
    name: str
    role: Literal["farmer", "buyer", "exporter"] = "buyer"
    phone: str
    location: Optional[str] = None

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = (v or "").strip()
        if not 2 <= len(v) <= 50:
            raise ValueError(ERR["name_len"])
        if not NAME_RE.match(v):
            raise ValueError(ERR["name_chars"])
        return v

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str) -> str:
        v = (v or "").strip().replace(" ", "").replace("-", "")
        if v.startswith("+91"):
            v = v[3:]
        if v.startswith("91") and len(v) == 12:
            v = v[2:]
        if not MOBILE_INDIA_RE.match(v):
            raise ValueError(ERR["mobile_format"])
        return v

    @field_validator("password")
    @classmethod
    def _pw(cls, v: str) -> str:
        _validate_password(v)
        return v

    @field_validator("confirm_password")
    @classmethod
    def _confirm(cls, v: str, info) -> str:
        if v != info.data.get("password"):
            raise ValueError(ERR["pwd_mismatch"])
        return v


class RegisterVerifyReq(BaseModel):
    otp_session: str
    code: str

    @field_validator("code")
    @classmethod
    def _code(cls, v: str) -> str:
        v = (v or "").strip()
        if not v.isdigit() or len(v) != 6:
            raise ValueError(ERR["otp_invalid"])
        return v


class RegisterResendReq(BaseModel):
    otp_session: str


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


class ChangePasswordReq(BaseModel):
    current_password: str
    new_password: str
    confirm_new_password: str
    logout_other_devices: bool = True


class ForgotPasswordOtpReq(BaseModel):
    email: EmailStr


class ResetPasswordOtpVerifyReq(BaseModel):
    otp_session: str
    code: str
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
    rating_avg: Optional[float] = 0.0
    rating_count: Optional[int] = 0
    active: bool = True
    pincode: Optional[str] = None
    weight_per_unit_kg: float = 1.0
    seller_delivery_charge: Optional[float] = None  # farmer-set flat fee; None = seller delivery not offered
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
    pincode: Optional[str] = None
    weight_per_unit_kg: float = 1.0
    seller_delivery_charge: Optional[float] = None


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
    delivery_method: DeliveryMethod = "courier"
    buyer_pincode: Optional[str] = None
    vehicle_type: Optional[VehicleType] = None


class Order(BaseModel):
    model_config = ConfigDict(extra="ignore")
    order_id: str
    buyer_id: str
    buyer_name: str
    items: List[OrderItem]
    total: float
    charge_total: Optional[float] = None
    delivery_address: str
    delivery_method: str = "courier"
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


class ReviewCreateReq(BaseModel):
    order_id: str
    product_id: str
    rating: int
    title: Optional[str] = ""
    body: Optional[str] = ""
    images: List = []


class ReviewUpdateReq(BaseModel):
    rating: Optional[int] = None
    title: Optional[str] = None
    body: Optional[str] = None
    images: Optional[List] = None


class ReviewReplyReq(BaseModel):
    body: str


class ReviewReportReq(BaseModel):
    reason: Optional[str] = "inappropriate"


class AdminUserUpdateReq(BaseModel):
    role: Optional[Literal["farmer", "buyer", "exporter", "admin", "delivery_partner", "super_admin"]] = None
    banned: Optional[bool] = None


class AdminProductUpdateReq(BaseModel):
    model_config = ConfigDict(extra="ignore")
    title: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    price: Optional[float] = None
    available_qty: Optional[int] = None
    quality_grade: Optional[Literal["A", "B", "C", "Export"]] = None
    active: Optional[bool] = None


class AdminOrderUpdateReq(BaseModel):
    status: Literal["placed", "confirmed", "shipped", "delivered", "cancelled"]


class AdminSettingsUpdateReq(BaseModel):
    platform_fee_percent: Optional[float] = None
    delivery_charge: Optional[float] = None


class CategoryReq(BaseModel):
    id: str
    name: str
    icon: str = "Leaf"


class BannerReq(BaseModel):
    title: str
    image_url: str
    link: Optional[str] = None
    active: bool = True
    sort_order: int = 0


class ReviewModerateReq(BaseModel):
    action: Literal["publish", "hide", "delete"]


# ------------------ Helpers ------------------
def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def hash_pw(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()


def verify_pw(pw: str, hashed: str) -> bool:
    return bcrypt.checkpw(pw.encode(), hashed.encode())


def make_jwt(user_id: str, pw_version: int = 0) -> str:
    payload: dict = {"user_id": user_id, "pwv": pw_version, "exp": datetime.now(timezone.utc) + timedelta(days=7)}
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


def check_password_strength(pw: str) -> None:
    """Same policy as registration (8+ chars, upper, lower, digit, symbol),
    usable outside a pydantic validator context (change/reset-password)."""
    try:
        _validate_password(pw)
    except ValueError as e:
        raise HTTPException(400, str(e))


async def log_security_event(event_type: str, *, user_id: Optional[str] = None, email: Optional[str] = None,
                              ip: Optional[str] = None, detail: Optional[str] = None) -> None:
    await db.security_logs.insert_one({
        "log_id": f"seclog_{uuid.uuid4().hex[:12]}",
        "event_type": event_type,  # password_changed | password_reset_requested | password_reset_completed
                                    # | login_failed | account_locked | suspicious_login
        "user_id": user_id,
        "email": email,
        "ip": ip,
        "detail": detail,
        "created_at": now_iso(),
    })


async def log_admin_activity(admin, action: str, *, target_type: Optional[str] = None,
                              target_id: Optional[str] = None, detail: Optional[str] = None) -> None:
    """Every Super Admin / Admin mutation gets recorded here for accountability."""
    await db.admin_activity_logs.insert_one({
        "log_id": f"actlog_{uuid.uuid4().hex[:12]}",
        "admin_id": admin.user_id,
        "admin_name": admin.name,
        "admin_role": admin.role,
        "action": action,
        "target_type": target_type,
        "target_id": target_id,
        "detail": detail,
        "created_at": now_iso(),
    })


PASSWORD_CHANGED_EMAIL_HTML = """<p>Hi {name},</p>
<p>Your KisanBaazar account password was just changed. If this was you, no action is needed.</p>
<p>If you did <b>not</b> make this change, please reset your password immediately and contact support.</p>
<p>— KisanBaazar Security</p>"""

RESET_REQUESTED_EMAIL_HTML = """<p>Hi,</p>
<p>We received a request to reset the password for this KisanBaazar account.</p>
<p><a href="{link}">Click here to reset your password</a> — this link expires in 15 minutes.</p>
<p>If you didn't request this, you can safely ignore this email — your password will not change.</p>
<p>— KisanBaazar Security</p>"""

RESET_COMPLETED_EMAIL_HTML = """<p>Hi {name},</p>
<p>Your KisanBaazar password was successfully reset. You've been logged out of all other devices for security.</p>
<p>If you did not do this, please contact support immediately.</p>
<p>— KisanBaazar Security</p>"""


def _user_id_from_jwt(token: str) -> Optional[str]:
    try:
        payload = pyjwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        return payload.get("user_id")
    except Exception:
        return None


def _jwt_pwv(token: str) -> Optional[int]:
    try:
        payload = pyjwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        return payload.get("pwv")
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
    token_pwv: Optional[int] = None

    if kb_token:
        user_id = _user_id_from_jwt(kb_token)
        token_pwv = _jwt_pwv(kb_token)

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
    if user_doc.get("banned"):
        raise HTTPException(403, "This account has been suspended | हे खाते निलंबित करण्यात आले आहे")
    if token_pwv is not None and token_pwv != user_doc.get("pw_version", 0):
        raise HTTPException(401, "Session expired — password was changed. Please log in again.")
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


# ------------------ Maintenance mode middleware ------------------
MAINTENANCE_EXEMPT_PREFIXES = ("/api/auth", "/api/admin", "/api/maintenance-status", "/api/site-content", "/api/settings")


@app.middleware("http")
async def maintenance_mode_middleware(request: Request, call_next):
    """While maintenance mode is on, block write operations from anyone who
    isn't an admin/super_admin. Reads (GET) and auth/admin endpoints always
    pass through so admins can still sign in and manage the site."""
    if request.method != "GET":
        path = request.url.path
        if not any(path.startswith(p) for p in MAINTENANCE_EXEMPT_PREFIXES):
            m = await get_maintenance()
            if m["enabled"]:
                token = request.cookies.get(AUTH_COOKIE)
                user_id = _user_id_from_jwt(token) if token else None
                allowed = False
                if user_id:
                    u = await db.users.find_one({"user_id": user_id}, {"_id": 0, "role": 1})
                    allowed = bool(u and is_admin_role(u.get("role", "")))
                if not allowed:
                    return JSONResponse(status_code=503, content={"detail": m["message"]})
    return await call_next(request)


def _otp_email_html(name: str, code: str) -> tuple[str, str]:
    """Return (html, text) for the OTP email — bilingual EN/MR, mobile-friendly.
    Uses inline CSS + a single table (email-client friendly)."""
    safe_name = (name or "there").split(" ")[0][:24]
    html = f"""\
<!DOCTYPE html>
<html><body style="margin:0;padding:0;background:#f5f7f4;font-family:Arial,sans-serif;color:#111">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f5f7f4;padding:24px 0">
  <tr><td align="center">
    <table role="presentation" width="480" cellpadding="0" cellspacing="0" style="background:#fff;border-radius:16px;overflow:hidden">
      <tr><td style="background:#16a34a;padding:20px 24px;color:#fff">
        <div style="font-size:22px;font-weight:800;letter-spacing:.3px">KisanBaazar</div>
        <div style="font-size:12px;opacity:.85">Agriculture Marketplace · कृषी बाजार</div>
      </td></tr>
      <tr><td style="padding:28px 24px">
        <p style="margin:0 0 12px;font-size:16px">Hi {safe_name},</p>
        <p style="margin:0 0 20px;font-size:14px;color:#555">
          Use this One-Time Password to complete your registration.<br/>
          <span style="color:#16a34a">तुमची नोंदणी पूर्ण करण्यासाठी हा OTP वापरा.</span>
        </p>
        <div style="text-align:center;margin:24px 0">
          <div style="display:inline-block;background:#f0fdf4;border:2px dashed #16a34a;color:#111;font-size:36px;letter-spacing:12px;font-weight:800;padding:16px 24px;border-radius:12px">
            {code}
          </div>
        </div>
        <p style="margin:0 0 8px;font-size:13px;color:#555">
          This code expires in <b>10 minutes</b>. Do not share it with anyone — KisanBaazar staff will never ask for your OTP.<br/>
          <span style="color:#777">हा कोड <b>10 मिनिटांत</b> संपेल. तो कोणालाही शेअर करू नका.</span>
        </p>
        <p style="margin:24px 0 0;font-size:12px;color:#999">If you didn't try to register on KisanBaazar, you can safely ignore this email.</p>
      </td></tr>
      <tr><td style="background:#0f172a;color:#94a3b8;padding:14px 24px;font-size:11px;text-align:center">
        © KisanBaazar · Direct from farm. सरळ शेतकऱ्यांकडून.
      </td></tr>
    </table>
  </td></tr>
</table>
</body></html>"""
    text = (
        f"KisanBaazar OTP\n\nHi {safe_name},\n\n"
        f"Your one-time password is: {code}\n"
        f"तुमचा वन-टाइम पासवर्ड: {code}\n\n"
        f"This code expires in 10 minutes.\n"
        f"Do not share it with anyone.\n"
    )
    return html, text


async def _mobile_taken(phone: str) -> bool:
    return await db.users.find_one({"phone": phone}, {"_id": 0, "user_id": 1}) is not None


# ------------------ Site settings (platform fee / delivery charge) ------------------
SETTINGS_DOC_ID = "site_settings"
DEFAULT_SETTINGS = {
    "settings_id": SETTINGS_DOC_ID,
    "platform_fee_percent": 1.0,   # matches the previous hardcoded *1.01 behaviour
    "delivery_charge": 0.0,
}


async def get_settings() -> dict:
    doc = await db.settings.find_one({"settings_id": SETTINGS_DOC_ID}, {"_id": 0})
    if not doc:
        return dict(DEFAULT_SETTINGS)
    return {**DEFAULT_SETTINGS, **doc}


# ------------------ Website Content (Super Admin CMS) ------------------
SITE_CONTENT_DOC_ID = "site_content"
DEFAULT_SITE_CONTENT = {
    "content_id": SITE_CONTENT_DOC_ID,
    "site_name": "KisanBaazar",
    "site_description": "Connecting India's farmers directly to the world. Transparent. Trusted. Trade.",
    "logo_url": None,
    "contact_email": "hello@kisanbaazar.in",
    "contact_phone": "1800-KISAN-00",
    "contact_address": "Pune, Maharashtra",
    "footer_text": "Made with 🌾 for Indian farmers",
    "social_links": {"facebook": "", "instagram": "", "twitter": "", "youtube": "", "whatsapp": ""},
}


async def get_site_content() -> dict:
    doc = await db.site_content.find_one({"content_id": SITE_CONTENT_DOC_ID}, {"_id": 0})
    if not doc:
        return dict(DEFAULT_SITE_CONTENT)
    merged = {**DEFAULT_SITE_CONTENT, **doc}
    merged["social_links"] = {**DEFAULT_SITE_CONTENT["social_links"], **doc.get("social_links", {})}
    return merged


class SocialLinks(BaseModel):
    facebook: str = ""
    instagram: str = ""
    twitter: str = ""
    youtube: str = ""
    whatsapp: str = ""


class SiteContentUpdateReq(BaseModel):
    site_name: Optional[str] = None
    site_description: Optional[str] = None
    logo_url: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    contact_address: Optional[str] = None
    footer_text: Optional[str] = None
    social_links: Optional[SocialLinks] = None


# ------------------ Maintenance Mode ------------------
MAINTENANCE_DOC_ID = "maintenance"
DEFAULT_MAINTENANCE = {"maintenance_id": MAINTENANCE_DOC_ID, "enabled": False, "message": "We'll be back shortly — KisanBaazar is undergoing scheduled maintenance."}


async def get_maintenance() -> dict:
    doc = await db.maintenance.find_one({"maintenance_id": MAINTENANCE_DOC_ID}, {"_id": 0})
    if not doc:
        return dict(DEFAULT_MAINTENANCE)
    return {**DEFAULT_MAINTENANCE, **doc}


class MaintenanceUpdateReq(BaseModel):
    enabled: bool
    message: Optional[str] = None


# ------------------ Hybrid Delivery System ------------------
def _pincode_zone(buyer_pin: Optional[str], farmer_pin: Optional[str]) -> str:
    """Rough distance/zone proxy from pincodes (no external geocoding available).
    same -> same locality, same_dist -> same first-3-digit postal district,
    same_state -> same first-digit postal region, other -> different region."""
    if not buyer_pin or not farmer_pin or len(buyer_pin) < 6 or len(farmer_pin) < 6:
        return "other"
    if buyer_pin == farmer_pin:
        return "same"
    if buyer_pin[:3] == farmer_pin[:3]:
        return "same_dist"
    if buyer_pin[0] == farmer_pin[0]:
        return "same_state"
    return "other"


ZONE_DISTANCE_KM = {"same": 5, "same_dist": 20, "same_state": 120, "other": 500}
ZONE_COURIER_MULTIPLIER = {"same": 1.0, "same_dist": 1.0, "same_state": 1.3, "other": 1.8}
VEHICLE_RATE_PER_KM = {"mini_truck": 12, "tempo": 18, "truck": 28}


def pick_vehicle_type(weight_kg: float) -> str:
    if weight_kg <= 50:
        return "mini_truck"
    if weight_kg <= 500:
        return "tempo"
    return "truck"


def calculate_delivery_charge(
    method: str,
    weight_kg: float,
    buyer_pincode: Optional[str] = None,
    farmer_pincode: Optional[str] = None,
    vehicle_type: Optional[str] = None,
    seller_charge: Optional[float] = None,
) -> tuple:
    """Returns (charge, meta) — meta carries the numbers used, for transparency in the UI/order record."""
    weight_kg = max(weight_kg, 0.1)
    zone = _pincode_zone(buyer_pincode, farmer_pincode)
    distance_km = ZONE_DISTANCE_KM[zone]

    if method == "pickup":
        return 0.0, {"zone": zone}

    if method == "seller_delivery":
        charge = float(seller_charge) if seller_charge is not None else 0.0
        return round(charge, 2), {"zone": zone, "seller_set": True}

    if method == "local_delivery":
        base = 20.0
        charge = base + distance_km * 5 + weight_kg * 2
        return round(charge, 2), {"zone": zone, "distance_km": distance_km, "weight_kg": weight_kg}

    if method == "courier":
        if weight_kg <= 1:
            base = 40.0
        elif weight_kg <= 5:
            base = 80.0
        elif weight_kg <= 10:
            base = 150.0
        else:
            base = 150.0 + (weight_kg - 10) * 15
        charge = base * ZONE_COURIER_MULTIPLIER[zone]
        return round(charge, 2), {"zone": zone, "weight_kg": weight_kg}

    if method == "transport":
        vt = vehicle_type or pick_vehicle_type(weight_kg)
        rate = VEHICLE_RATE_PER_KM.get(vt, VEHICLE_RATE_PER_KM["tempo"])
        charge = distance_km * rate + weight_kg * 3
        return round(charge, 2), {"zone": zone, "distance_km": distance_km, "vehicle_type": vt, "weight_kg": weight_kg}

    return 0.0, {"zone": zone}


class DeliveryEstimateReq(BaseModel):
    method: DeliveryMethod
    product_id: str
    qty: int = 1
    buyer_pincode: Optional[str] = None
    vehicle_type: Optional[VehicleType] = None


class DeliveryAssignReq(BaseModel):
    delivery_partner_id: str


class DeliveryStatusReq(BaseModel):
    status: Literal["assigned", "picked_up", "in_transit", "out_for_delivery", "delivered"]
    otp: Optional[str] = None
    note: Optional[str] = None


# ------------------ Auth Routes ------------------
@api.post("/auth/register/init")
async def register_init(req: RegisterInitReq):
    """Step 1: validate the registration payload, check duplicates, generate
    an OTP session and send the code via email. Returns `otp_session` +
    delivery hint. No user is created at this point."""
    email = req.email.lower()
    if await db.users.find_one({"email": email}, {"_id": 0, "user_id": 1}):
        raise HTTPException(409, ERR["email_taken"])
    if await _mobile_taken(req.phone):
        raise HTTPException(409, ERR["mobile_taken"])

    # Snapshot the pending payload — password already hashed here so plaintext
    # never leaves this call site.
    payload = {
        "email": email,
        "password_hash": hash_pw(req.password),
        "name": req.name,
        "role": req.role,
        "phone": req.phone,
        "location": req.location,
    }
    session_id, code = await otp_service.create(
        db, purpose="register", email=email, payload=payload,
    )
    html, text = _otp_email_html(req.name, code)
    delivery = await send_email(
        to=email, subject="Your KisanBaazar OTP · तुमचा OTP", html=html, text=text,
    )
    return {
        "otp_session": session_id,
        "email": email,
        "expires_in_seconds": int(otp_service.OTP_TTL.total_seconds()),
        "resend_cooldown_seconds": int(otp_service.RESEND_COOLDOWN.total_seconds()),
        "mock_delivery": delivery.get("mock", False),
    }


@api.post("/auth/register/resend-otp")
async def register_resend_otp(req: RegisterResendReq):
    """Step 1.5: rotate + resend OTP for an existing pending session.
    Enforces 60s cooldown at the service layer."""
    try:
        new_code, row = await otp_service.resend(db, session_id=req.otp_session)
    except ValueError as e:
        msg = str(e)
        if msg == "session_not_found":
            raise HTTPException(404, ERR["session_gone"])
        if msg == "expired":
            raise HTTPException(410, ERR["otp_expired"])
        if msg.startswith("cooldown:"):
            secs = msg.split(":", 1)[1]
            raise HTTPException(429, ERR["otp_cooldown"].format(s=secs))
        raise HTTPException(400, msg)
    name = (row.get("email") or "").split("@")[0]
    html, text = _otp_email_html(name, new_code)
    delivery = await send_email(
        to=row["email"], subject="Your KisanBaazar OTP · तुमचा OTP",
        html=html, text=text,
    )
    return {
        "otp_session": req.otp_session,
        "email": row["email"],
        "resend_count": row["resend_count"],
        "mock_delivery": delivery.get("mock", False),
    }


@api.post("/auth/register/verify-otp")
async def register_verify_otp(req: RegisterVerifyReq, response: Response):
    """Step 2: verify the OTP and, on success, atomically create the user
    account + sign them in (sets httpOnly JWT cookie + returns CSRF token)."""
    try:
        payload = await otp_service.verify(
            db, session_id=req.otp_session, code=req.code,
        )
    except ValueError as e:
        msg = str(e)
        if msg == "session_not_found":
            raise HTTPException(404, ERR["session_gone"])
        if msg == "expired":
            raise HTTPException(410, ERR["otp_expired"])
        if msg == "too_many_attempts":
            raise HTTPException(429, ERR["otp_max"])
        if msg.startswith("invalid_code:"):
            remaining = msg.split(":", 1)[1]
            raise HTTPException(400, f'{ERR["otp_invalid"]} ({remaining} left)')
        if msg.startswith("already_consumed:"):
            # This OTP session already succeeded once — e.g. a double-tap on
            # "Verify & Create", or a client retry after a slow Render
            # cold-start response that actually completed server-side. The
            # account already exists; log the user in instead of showing a
            # false "verification failed" error.
            already_email = msg.split(":", 1)[1]
            existing = await db.users.find_one({"email": already_email}, {"_id": 0})
            if existing:
                token = make_jwt(existing["user_id"], existing.get("pw_version", 0))
                csrf = _set_auth_cookies(response, token)
                return {"user": public_user(existing), "csrf_token": csrf}
            raise HTTPException(400, ERR["otp_invalid"])
        raise HTTPException(400, ERR["otp_invalid"])

    email = payload["_email"]
    # Race-check duplicates once more (someone could have registered in the
    # ~10 minute window since /init).
    if await db.users.find_one({"email": email}, {"_id": 0, "user_id": 1}):
        raise HTTPException(409, ERR["email_taken"])
    if payload.get("phone") and await _mobile_taken(payload["phone"]):
        raise HTTPException(409, ERR["mobile_taken"])

    user_id = f"user_{uuid.uuid4().hex[:12]}"
    doc = {
        "user_id": user_id,
        "email": email,
        "password": payload["password_hash"],
        "name": payload["name"],
        "role": payload["role"],
        "phone": payload.get("phone"),
        "location": payload.get("location"),
        "picture": None,
        "verified": True,  # email verified via OTP
        "created_at": now_iso(),
    }
    await db.users.insert_one(doc)
    token = make_jwt(user_id)
    csrf = _set_auth_cookies(response, token)
    return {"user": public_user(doc), "csrf_token": csrf}


@api.post("/auth/register")
async def register(req: RegisterReq, response: Response):
    """Legacy direct-register (no OTP). Kept for backwards compatibility with
    existing tests/tools. **New signups should use /auth/register/init +
    /auth/register/verify-otp.**"""
    email = req.email.lower()
    existing = await db.users.find_one({"email": email}, {"_id": 0})
    if existing:
        raise HTTPException(400, ERR["email_taken"])
    if req.phone and await _mobile_taken(req.phone):
        raise HTTPException(400, ERR["mobile_taken"])
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
        await log_security_event("login_failed", email=email, ip=get_client_ip(request),
                                  detail=f"attempt {attempts}")
        remaining = max(0, LOCK_THRESHOLD - attempts)
        if remaining == 0:
            await log_security_event("account_locked", user_id=user.get("user_id") if user else None,
                                      email=email, ip=get_client_ip(request))
            if user:
                await send_email(
                    to=email, subject="KisanBaazar — Multiple failed login attempts",
                    html=f"<p>Hi {user.get('name', '')},</p><p>Your account had {attempts} failed login "
                         f"attempts and has been temporarily locked for 15 minutes for your security. "
                         f"If this wasn't you, consider resetting your password.</p><p>— KisanBaazar Security</p>",
                )
            raise HTTPException(
                status_code=429,
                detail="Too many failed attempts. Account locked for 15 minutes.",
                headers={"Retry-After": str(int(LOCK_DURATION.total_seconds()))},
            )
        if remaining <= 2:
            raise HTTPException(401, f"Invalid credentials ({remaining} attempt{'s' if remaining != 1 else ''} remaining)")
        raise HTTPException(401, "Invalid credentials")

    await clear_attempts(identifier)
    token = make_jwt(user["user_id"], user.get("pw_version", 0))
    csrf = _set_auth_cookies(response, token)
    return {"user": public_user(user), "csrf_token": csrf}


@api.get("/auth/me")
async def me(response: Response, user: User = Depends(get_current_user), csrf_token: Optional[str] = Cookie(None)):
    # Ensure CSRF cookie exists for any authenticated session (covers legacy logins)
    if not csrf_token:
        new_csrf = secrets.token_urlsafe(32)
        response.set_cookie(
            CSRF_COOKIE, new_csrf,
            httponly=False, secure=True, samesite="none", path="/", max_age=COOKIE_MAX_AGE,
            domain=COOKIE_DOMAIN,
        )
    return user


@api.post("/auth/csrf")
async def issue_csrf(response: Response):
    """Issue (or rotate) a CSRF token. Safe to call before login as well."""
    csrf = secrets.token_urlsafe(32)
    response.set_cookie(
        CSRF_COOKIE, csrf,
        httponly=False, secure=True, samesite="none", path="/", max_age=COOKIE_MAX_AGE,
        domain=COOKIE_DOMAIN,
    )
    return {"csrf_token": csrf}


@api.post("/auth/logout")
async def logout(response: Response, session_token: Optional[str] = Cookie(None)):
    if session_token:
        await db.user_sessions.delete_one({"session_token": session_token})
    _clear_auth_cookies(response)
    return {"ok": True}


@api.post("/auth/forgot-password")
async def forgot_password(req: ForgotPasswordReq, request: Request):
    """Issue a single-use reset token (15 min TTL). Always returns the same
    response regardless of whether the account exists, to prevent email
    enumeration. Rate-limited per email to slow down abuse."""
    email = req.email.lower()
    ip = get_client_ip(request)

    # Rate limit: max RESET_REQUEST_LIMIT requests per RESET_REQUEST_WINDOW per email.
    window_start = datetime.now(timezone.utc) - RESET_REQUEST_WINDOW
    recent = await db.password_reset_requests.count_documents({"email": email, "created_at": {"$gte": window_start}})
    if recent >= RESET_REQUEST_LIMIT:
        # Still return the generic response — don't reveal rate-limit state to a potential attacker.
        return {"ok": True, "message": "If an account exists for that email, a reset link has been sent."}
    await db.password_reset_requests.insert_one({"email": email, "ip": ip, "created_at": datetime.now(timezone.utc)})

    user = await db.users.find_one({"email": email}, {"_id": 0})
    if user:
        # Invalidate any previously issued, still-unused tokens — only one active token at a time.
        await db.password_reset_tokens.update_many(
            {"user_id": user["user_id"], "used": False}, {"$set": {"used": True, "used_at": now_iso()}},
        )
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
        await send_email(
            to=email, subject="Reset your KisanBaazar password",
            html=RESET_REQUESTED_EMAIL_HTML.format(link=reset_link),
            text=f"Reset your password: {reset_link} (expires in 15 minutes)",
        )
        await log_security_event("password_reset_requested", user_id=user["user_id"], email=email, ip=ip)
    return {"ok": True, "message": "If an account exists for that email, a reset link has been sent."}


@api.post("/auth/reset-password")
async def reset_password(req: ResetPasswordReq, request: Request):
    check_password_strength(req.new_password)
    rec = await db.password_reset_tokens.find_one({"token": req.token})
    if not rec or rec.get("used"):
        raise HTTPException(400, "Invalid or expired reset token")
    expires_at = await _ensure_aware(rec["expires_at"])
    if expires_at < datetime.now(timezone.utc):
        raise HTTPException(400, "Invalid or expired reset token")

    user = await db.users.find_one({"user_id": rec["user_id"]}, {"_id": 0})
    if not user:
        raise HTTPException(400, "Invalid or expired reset token")
    _reject_if_password_reused(req.new_password, user)

    await db.users.update_one(
        {"user_id": rec["user_id"]},
        {
            "$set": {"password": hash_pw(req.new_password)},
            "$inc": {"pw_version": 1},  # invalidates every previously issued JWT — logs out all devices
            "$push": {"password_history": {"$each": [user.get("password", "")], "$slice": -PASSWORD_HISTORY_LIMIT}},
        },
    )
    # Single-use: mark this token used, and invalidate any other outstanding tokens for this user too.
    await db.password_reset_tokens.update_many(
        {"user_id": rec["user_id"], "used": False}, {"$set": {"used": True, "used_at": now_iso()}},
    )
    await clear_attempts_for_email(rec["email"])
    await send_email(
        to=rec["email"], subject="Your KisanBaazar password was reset",
        html=RESET_COMPLETED_EMAIL_HTML.format(name=user.get("name", "")),
    )
    await log_security_event("password_reset_completed", user_id=rec["user_id"], email=rec["email"], ip=get_client_ip(request))
    return {"ok": True, "message": "Password updated. You can now log in."}


@api.post("/auth/forgot-password/otp")
async def forgot_password_otp(req: ForgotPasswordOtpReq, request: Request):
    """Email-OTP alternative to the reset-link flow — same rate limiting and
    generic response to avoid revealing whether the account exists."""
    email = req.email.lower()
    window_start = datetime.now(timezone.utc) - RESET_REQUEST_WINDOW
    recent = await db.password_reset_requests.count_documents({"email": email, "created_at": {"$gte": window_start}})
    if recent < RESET_REQUEST_LIMIT:
        await db.password_reset_requests.insert_one({"email": email, "ip": get_client_ip(request), "created_at": datetime.now(timezone.utc)})
        user = await db.users.find_one({"email": email}, {"_id": 0, "user_id": 1})
        if user:
            session_id, code = await otp_service.create(db, purpose="reset-password", email=email, payload={"user_id": user["user_id"]})
            await send_email(
                to=email, subject="Your KisanBaazar password reset code",
                html=f"<p>Your password reset code is:</p><h2 style='letter-spacing:4px'>{code}</h2><p>This code expires in 10 minutes.</p>",
                text=f"Your password reset code: {code} (expires in 10 minutes)",
            )
            await log_security_event("password_reset_requested", user_id=user["user_id"], email=email, ip=get_client_ip(request))
            return {"ok": True, "otp_session": session_id, "message": "If an account exists for that email, a code has been sent."}
    return {"ok": True, "otp_session": None, "message": "If an account exists for that email, a code has been sent."}


@api.post("/auth/reset-password/otp/verify")
async def reset_password_otp_verify(req: ResetPasswordOtpVerifyReq, request: Request):
    check_password_strength(req.new_password)
    try:
        payload = await otp_service.verify(db, session_id=req.otp_session, code=req.code)
    except ValueError as e:
        msg = str(e)
        if msg == "session_not_found":
            raise HTTPException(404, ERR["session_gone"])
        if msg == "expired":
            raise HTTPException(410, ERR["otp_expired"])
        if msg == "too_many_attempts":
            raise HTTPException(429, ERR["otp_max"])
        raise HTTPException(400, ERR["otp_invalid"])

    user_id = payload.get("user_id")
    user = await db.users.find_one({"user_id": user_id}, {"_id": 0})
    if not user:
        raise HTTPException(400, "Account not found")
    _reject_if_password_reused(req.new_password, user)

    await db.users.update_one(
        {"user_id": user_id},
        {
            "$set": {"password": hash_pw(req.new_password)},
            "$inc": {"pw_version": 1},
            "$push": {"password_history": {"$each": [user.get("password", "")], "$slice": -PASSWORD_HISTORY_LIMIT}},
        },
    )
    await clear_attempts_for_email(user["email"])
    await send_email(
        to=user["email"], subject="Your KisanBaazar password was reset",
        html=RESET_COMPLETED_EMAIL_HTML.format(name=user.get("name", "")),
    )
    await log_security_event("password_reset_completed", user_id=user_id, email=user["email"], ip=get_client_ip(request))
    return {"ok": True, "message": "Password updated. You can now log in."}


def _reject_if_password_reused(new_password: str, user: dict) -> None:
    history = user.get("password_history", []) + ([user["password"]] if user.get("password") else [])
    for old_hash in history:
        if old_hash and verify_pw(new_password, old_hash):
            raise HTTPException(400, "You've used this password before — please choose a different one")


@api.post("/auth/change-password")
async def change_password(req: ChangePasswordReq, request: Request, response: Response, user: User = Depends(get_current_user)):
    if req.new_password != req.confirm_new_password:
        raise HTTPException(400, ERR["pwd_mismatch"])
    check_password_strength(req.new_password)
    doc = await db.users.find_one({"user_id": user.user_id}, {"_id": 0})
    if not doc or "password" not in doc or not verify_pw(req.current_password, doc["password"]):
        raise HTTPException(400, "Current password is incorrect")
    _reject_if_password_reused(req.new_password, doc)

    new_pwv = doc.get("pw_version", 0) + (1 if req.logout_other_devices else 0)
    await db.users.update_one(
        {"user_id": user.user_id},
        {
            "$set": {"password": hash_pw(req.new_password), "pw_version": new_pwv},
            "$push": {"password_history": {"$each": [doc["password"]], "$slice": -PASSWORD_HISTORY_LIMIT}},
        },
    )
    await send_email(
        to=doc["email"], subject="Your KisanBaazar password was changed",
        html=PASSWORD_CHANGED_EMAIL_HTML.format(name=doc.get("name", "")),
    )
    await log_security_event("password_changed", user_id=user.user_id, email=doc["email"], ip=get_client_ip(request))

    if req.logout_other_devices:
        # Re-issue a fresh cookie for *this* session so the user isn't logged out of the tab they're using.
        token = make_jwt(user.user_id, new_pwv)
        _set_auth_cookies(response, token)
    return {"ok": True, "message": "Password changed successfully."}


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
        max_age=COOKIE_MAX_AGE, domain=COOKIE_DOMAIN,
    )
    csrf = secrets.token_urlsafe(32)
    response.set_cookie(
        CSRF_COOKIE, csrf, httponly=False, secure=True, samesite="none", path="/",
        max_age=COOKIE_MAX_AGE, domain=COOKIE_DOMAIN,
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
    docs = await db.categories.find({}, {"_id": 0}).sort("name", 1).to_list(200)
    return docs if docs else CATEGORIES


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
    query = {"active": {"$ne": False}}
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
        "active": True,
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
    if prod["farmer_id"] != user.user_id and not is_admin_role(user.role):
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
    pincode: Optional[str] = None
    weight_per_unit_kg: Optional[float] = None
    seller_delivery_charge: Optional[float] = None
async def update_product(pid: str, req: ProductUpdate, user: User = Depends(get_current_user)):
    prod = await db.products.find_one({"product_id": pid}, {"_id": 0})
    if not prod:
        raise HTTPException(404, "Not found")
    if prod["farmer_id"] != user.user_id and not is_admin_role(user.role):
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

    if not is_admin_role(user.role) and not cloudinary_user_owns(pid, user.user_id):
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
    cfg = await get_settings()
    fee_percent = cfg["platform_fee_percent"]

    # Look up product docs for weight/pincode/seller-delivery-charge — the
    # client only sends product_id/qty/price, so delivery math is computed
    # server-side from trusted data.
    pids = [it.product_id for it in req.items]
    prod_docs = await db.products.find({"product_id": {"$in": pids}}, {"_id": 0}).to_list(len(pids) or 1)
    prod_by_id = {p["product_id"]: p for p in prod_docs}
    total_weight_kg = sum(
        it.qty * prod_by_id.get(it.product_id, {}).get("weight_per_unit_kg", 1.0) for it in req.items
    )
    primary_product = prod_by_id.get(req.items[0].product_id, {}) if req.items else {}
    farmer_pincode = primary_product.get("pincode")
    seller_charge = primary_product.get("seller_delivery_charge")

    delivery_charge, delivery_meta = calculate_delivery_charge(
        req.delivery_method, total_weight_kg,
        buyer_pincode=req.buyer_pincode, farmer_pincode=farmer_pincode,
        vehicle_type=req.vehicle_type, seller_charge=seller_charge,
    )
    charge_total = round(subtotal * (1 + fee_percent / 100) + delivery_charge)
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
        "platform_fee_percent": fee_percent,
        "delivery_charge": delivery_charge,
        "delivery_method": req.delivery_method,
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

    # Create the linked delivery tracking record.
    eta_days = {"pickup": 0, "local_delivery": 1, "courier": 4, "transport": 5, "seller_delivery": 3}
    delivery_doc = {
        "delivery_id": f"del_{uuid.uuid4().hex[:10]}",
        "order_id": oid,
        "buyer_id": user.user_id,
        "farmer_id": primary_product.get("farmer_id"),
        "method": req.delivery_method,
        "status": "pending",
        "assigned_to": None,
        "otp": f"{secrets.randbelow(1000000):06d}",
        "charge": delivery_charge,
        "meta": delivery_meta,
        "buyer_pincode": req.buyer_pincode,
        "farmer_pincode": farmer_pincode,
        "estimated_delivery_date": (datetime.now(timezone.utc) + timedelta(days=eta_days.get(req.delivery_method, 3))).date().isoformat(),
        "tracking_history": [{"status": "pending", "at": now_iso(), "note": "Order placed"}],
        "created_at": now_iso(),
    }
    await db.deliveries.insert_one(delivery_doc)
    return doc


# ------------------ Delivery ------------------
@api.post("/delivery/estimate")
async def delivery_estimate(req: DeliveryEstimateReq, user: User = Depends(get_current_user)):
    """Live delivery-charge preview for the checkout page, before an order exists."""
    prod = await db.products.find_one({"product_id": req.product_id}, {"_id": 0})
    if not prod:
        raise HTTPException(404, "Product not found")
    weight_kg = req.qty * prod.get("weight_per_unit_kg", 1.0)
    charge, meta = calculate_delivery_charge(
        req.method, weight_kg,
        buyer_pincode=req.buyer_pincode, farmer_pincode=prod.get("pincode"),
        vehicle_type=req.vehicle_type, seller_charge=prod.get("seller_delivery_charge"),
    )
    return {"charge": charge, "meta": meta, "seller_delivery_available": prod.get("seller_delivery_charge") is not None}


def _delivery_access_ok(d: dict, user: User) -> bool:
    return is_admin_role(user.role) or user.user_id in (d.get("buyer_id"), d.get("farmer_id"), d.get("assigned_to"))


@api.get("/delivery/my-deliveries")
async def my_deliveries(user: User = Depends(get_current_user)):
    if user.role != "delivery_partner":
        raise HTTPException(403, "Delivery partners only")
    docs = await db.deliveries.find({"assigned_to": user.user_id}, {"_id": 0}).sort("created_at", -1).to_list(200)
    return docs


@api.get("/delivery/order/{order_id}")
async def get_delivery_for_order(order_id: str, user: User = Depends(get_current_user)):
    d = await db.deliveries.find_one({"order_id": order_id}, {"_id": 0})
    if not d:
        raise HTTPException(404, "Delivery record not found")
    if not _delivery_access_ok(d, user):
        raise HTTPException(403, "Forbidden")
    return d


@api.patch("/delivery/{did}/assign")
async def assign_delivery(did: str, req: DeliveryAssignReq, user: User = Depends(get_current_user)):
    d = await db.deliveries.find_one({"delivery_id": did}, {"_id": 0})
    if not d:
        raise HTTPException(404, "Delivery not found")
    if not is_admin_role(user.role) and user.user_id != d.get("farmer_id"):
        raise HTTPException(403, "Only admin or the selling farmer can assign a delivery partner")
    partner = await db.users.find_one({"user_id": req.delivery_partner_id, "role": "delivery_partner"}, {"_id": 0})
    if not partner:
        raise HTTPException(404, "Delivery partner not found")
    await db.deliveries.update_one(
        {"delivery_id": did},
        {"$set": {"assigned_to": req.delivery_partner_id, "status": "assigned"},
         "$push": {"tracking_history": {"status": "assigned", "at": now_iso(), "note": f"Assigned to {partner['name']}"}}},
    )
    if is_admin_role(user.role):
        await log_admin_activity(user, "delivery_assigned", target_type="delivery", target_id=did, detail=partner["name"])
    return await db.deliveries.find_one({"delivery_id": did}, {"_id": 0})


@api.patch("/delivery/{did}/status")
async def update_delivery_status(did: str, req: DeliveryStatusReq, user: User = Depends(get_current_user)):
    d = await db.deliveries.find_one({"delivery_id": did}, {"_id": 0})
    if not d:
        raise HTTPException(404, "Delivery not found")
    if user.role not in ("admin", "delivery_partner") or (user.role == "delivery_partner" and user.user_id != d.get("assigned_to")):
        raise HTTPException(403, "Only the assigned delivery partner or admin can update status")
    if req.status == "delivered":
        if not req.otp or req.otp != d.get("otp"):
            raise HTTPException(400, "Incorrect delivery OTP — ask the buyer for the code shown on their order")
    updates = {"status": req.status}
    await db.deliveries.update_one(
        {"delivery_id": did},
        {"$set": updates,
         "$push": {"tracking_history": {"status": req.status, "at": now_iso(), "note": req.note or ""}}},
    )
    if req.status == "delivered":
        await db.orders.update_one({"order_id": d["order_id"]}, {"$set": {"status": "delivered"}})
    return await db.deliveries.find_one({"delivery_id": did}, {"_id": 0})


@api.get("/admin/deliveries")
async def admin_list_deliveries(
    status: Optional[str] = None, method: Optional[str] = None, limit: int = 300,
    user: User = Depends(get_current_user),
):
    if not is_admin_role(user.role):
        raise HTTPException(403, "Admin only")
    query: dict = {}
    if status:
        query["status"] = status
    if method:
        query["method"] = method
    return await db.deliveries.find(query, {"_id": 0}).sort("created_at", -1).to_list(limit)


@api.get("/admin/delivery-analytics")
async def admin_delivery_analytics(user: User = Depends(get_current_user)):
    if not is_admin_role(user.role):
        raise HTTPException(403, "Admin only")
    by_status = await db.deliveries.aggregate(
        [{"$group": {"_id": "$status", "count": {"$sum": 1}}}]
    ).to_list(20)
    by_method = await db.deliveries.aggregate(
        [{"$group": {"_id": "$method", "count": {"$sum": 1}, "total_charge": {"$sum": "$charge"}}}]
    ).to_list(20)
    return {
        "by_status": {r["_id"]: r["count"] for r in by_status},
        "by_method": {r["_id"]: {"count": r["count"], "total_charge": round(r["total_charge"], 2)} for r in by_method},
    }


# ------------------ Website Content (public + Super Admin) ------------------
@api.get("/site-content")
async def public_site_content():
    return await get_site_content()


@api.get("/admin/site-content")
async def admin_get_site_content(user: User = Depends(get_current_user)):
    require_super_admin(user)
    return await get_site_content()


@api.put("/admin/site-content")
async def admin_update_site_content(req: SiteContentUpdateReq, user: User = Depends(get_current_user)):
    require_super_admin(user)
    updates = {k: v for k, v in req.model_dump(exclude_none=True).items()}
    if not updates:
        raise HTTPException(400, "Nothing to update")
    await db.site_content.update_one({"content_id": SITE_CONTENT_DOC_ID}, {"$set": updates}, upsert=True)
    await log_admin_activity(user, "site_content_updated", target_type="site_content", detail=str(list(updates.keys())))
    return await get_site_content()


# ------------------ Maintenance Mode ------------------
@api.get("/maintenance-status")
async def public_maintenance_status():
    m = await get_maintenance()
    return {"enabled": m["enabled"], "message": m["message"]}


@api.get("/admin/maintenance")
async def admin_get_maintenance(user: User = Depends(get_current_user)):
    require_super_admin(user)
    return await get_maintenance()


@api.put("/admin/maintenance")
async def admin_update_maintenance(req: MaintenanceUpdateReq, user: User = Depends(get_current_user)):
    require_super_admin(user)
    updates = {"enabled": req.enabled}
    if req.message is not None:
        updates["message"] = req.message
    await db.maintenance.update_one({"maintenance_id": MAINTENANCE_DOC_ID}, {"$set": updates}, upsert=True)
    await log_admin_activity(user, "maintenance_mode_toggled", target_type="maintenance", detail=str(updates))
    return await get_maintenance()


# ------------------ Admin Activity Logs ------------------
@api.get("/admin/activity-logs")
async def admin_activity_logs(admin_id: Optional[str] = None, action: Optional[str] = None, limit: int = 300,
                               user: User = Depends(get_current_user)):
    require_super_admin(user)
    query: dict = {}
    if admin_id:
        query["admin_id"] = admin_id
    if action:
        query["action"] = action
    return await db.admin_activity_logs.find(query, {"_id": 0}).sort("created_at", -1).to_list(limit)


@api.get("/settings")
async def public_settings():
    """Public read-only site settings (platform fee %, delivery charge) so
    Cart/Checkout can compute totals the same way the backend will charge."""
    cfg = await get_settings()
    return {"platform_fee_percent": cfg["platform_fee_percent"], "delivery_charge": cfg["delivery_charge"]}


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
    query = {} if is_admin_role(user.role) else {"user_id": user.user_id}
    docs = await db.payments.find(query, {"_id": 0}).sort("created_at", -1).to_list(500)
    return docs


@api.get("/admin/payments")
async def admin_list_payments(
    status: Optional[str] = None,
    user: User = Depends(get_current_user),
):
    if not is_admin_role(user.role):
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
    if not is_admin_role(user.role):
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
    if not is_admin_role(user.role) and order["buyer_id"] != user.user_id:
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


# ------------------ Ratings & Reviews ------------------
@api.get("/reviews/eligible")
async def list_eligible_reviewable(user: User = Depends(get_current_user)):
    """Return paid orders where the buyer has unreviewed line items.
    Used by the Buyer Dashboard 'Write a review' surface."""
    paid_orders = await db.orders.find(
        {"buyer_id": user.user_id, "payment_status": "paid"}, {"_id": 0}
    ).sort("created_at", -1).to_list(200)
    reviewed = await db.reviews.find(
        {"buyer_id": user.user_id}, {"_id": 0, "order_id": 1, "product_id": 1}
    ).to_list(1000)
    reviewed_keys = {(r["order_id"], r["product_id"]) for r in reviewed}
    out: list = []
    for o in paid_orders:
        for it in o.get("items", []):
            pid = it.get("product_id")
            if pid and (o["order_id"], pid) not in reviewed_keys:
                out.append({
                    "order_id": o["order_id"],
                    "product_id": pid,
                    "product_title": it.get("title"),
                    "product_image": it.get("image"),
                    "created_at": o.get("created_at"),
                })
    return out


@api.post("/reviews")
async def post_review(req: ReviewCreateReq, user: User = Depends(get_current_user)):
    try:
        rev = await svc_create_review(
            db,
            buyer_id=user.user_id, buyer_name=user.name,
            order_id=req.order_id, product_id=req.product_id,
            rating=req.rating, title=req.title or "", body=req.body or "",
            images=req.images or [],
        )
    except ValueError as e:
        msg = str(e)
        code = 400 if msg in ("invalid_rating",) else 403 if msg == "not_eligible" else 404
        raise HTTPException(code, msg)
    return rev


@api.put("/reviews/{rid}")
async def edit_review(rid: str, req: ReviewUpdateReq, user: User = Depends(get_current_user)):
    try:
        return await svc_update_review(
            db, review_id=rid, buyer_id=user.user_id,
            rating=req.rating, title=req.title, body=req.body, images=req.images,
        )
    except ValueError as e:
        msg = str(e)
        code = 404 if msg == "not_found" else 403 if msg == "forbidden" else 400
        raise HTTPException(code, msg)


@api.get("/products/{pid}/reviews")
async def list_product_reviews(pid: str):
    docs = await db.reviews.find(
        {"product_id": pid, "status": "published"}, {"_id": 0, "reports": 0},
    ).sort("created_at", -1).to_list(200)
    return docs


@api.get("/farmers/{fid}/reviews")
async def list_farmer_reviews(fid: str):
    docs = await db.reviews.find(
        {"farmer_id": fid, "status": "published"}, {"_id": 0, "reports": 0},
    ).sort("created_at", -1).to_list(200)
    return docs


@api.get("/farmer/reviews")
async def my_farmer_reviews(user: User = Depends(get_current_user)):
    """Farmer view: every review on their products (incl. reported/hidden) so
    they can see + reply. Reply gating is enforced server-side on POST."""
    if user.role not in ("farmer", "admin"):
        raise HTTPException(403, "Farmer only")
    docs = await db.reviews.find(
        {"farmer_id": user.user_id}, {"_id": 0, "reports": 0},
    ).sort("created_at", -1).to_list(500)
    if docs:
        pids = list({d["product_id"] for d in docs})
        titles = {p["product_id"]: p.get("title", "") async for p in
                  db.products.find({"product_id": {"$in": pids}}, {"_id": 0, "product_id": 1, "title": 1})}
        for d in docs:
            d["product_title"] = titles.get(d["product_id"], "")
    return docs


@api.post("/reviews/{rid}/reply")
async def reply_review(rid: str, req: ReviewReplyReq, user: User = Depends(get_current_user)):
    if user.role != "farmer":
        raise HTTPException(403, "Only the farmer can reply")
    try:
        return await svc_reply_review(db, review_id=rid, farmer_id=user.user_id, body=req.body)
    except ValueError as e:
        msg = str(e)
        code = 404 if msg == "not_found" else 403 if msg == "forbidden" else 400
        raise HTTPException(code, msg)


@api.post("/reviews/{rid}/report")
async def report_review(rid: str, req: ReviewReportReq, user: User = Depends(get_current_user)):
    try:
        rev = await svc_report_review(
            db, review_id=rid, reporter_id=user.user_id, reason=req.reason or "inappropriate",
        )
    except ValueError as e:
        msg = str(e)
        code = 404 if msg == "not_found" else 409 if msg == "already_reported" else 400
        raise HTTPException(code, msg)
    return {"ok": True, "status": rev.get("status")}


@api.get("/admin/reviews")
async def admin_list_reviews(
    status: Optional[str] = None,
    user: User = Depends(get_current_user),
):
    if not is_admin_role(user.role):
        raise HTTPException(403, "Admin only")
    q: dict = {}
    if status:
        q["status"] = status
    docs = await db.reviews.find(q, {"_id": 0}).sort("created_at", -1).to_list(500)
    if docs:
        pids = list({d["product_id"] for d in docs})
        titles = {p["product_id"]: p.get("title", "") async for p in
                  db.products.find({"product_id": {"$in": pids}}, {"_id": 0, "product_id": 1, "title": 1})}
        for d in docs:
            d["product_title"] = titles.get(d["product_id"], "")
    return docs


@api.post("/admin/reviews/{rid}/moderate")
async def admin_moderate(rid: str, req: ReviewModerateReq, user: User = Depends(get_current_user)):
    if not is_admin_role(user.role):
        raise HTTPException(403, "Admin only")
    try:
        result = await svc_moderate_review(db, review_id=rid, action=req.action)
    except ValueError as e:
        raise HTTPException(404 if str(e) == "not_found" else 400, str(e))
    return {"ok": True, "deleted": result is None, "review": result}


@api.get("/orders")
async def list_orders(user: User = Depends(get_current_user)):
    docs: list = []
    if is_admin_role(user.role):
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
    if is_admin_role(user.role):
        return {
            "users": await db.users.count_documents({}),
            "products": await db.products.count_documents({}),
            "orders": await db.orders.count_documents({}),
            "revenue": sum([o["total"] async for o in db.orders.find({"payment_status": "paid"}, {"_id": 0, "total": 1})]),
        }
    orders = await db.orders.count_documents({"buyer_id": user.user_id})
    wishlist = await db.wishlist.count_documents({"user_id": user.user_id})
    return {"orders": orders, "wishlist": wishlist}


# ------------------ Admin: Users ------------------
@api.get("/admin/users")
async def admin_list_users(
    q: Optional[str] = None,
    role: Optional[str] = None,
    limit: int = 200,
    user: User = Depends(get_current_user),
):
    if not is_admin_role(user.role):
        raise HTTPException(403, "Admin only")
    query: dict = {}
    if role:
        query["role"] = role
    if q:
        query["$or"] = [
            {"name": {"$regex": q, "$options": "i"}},
            {"email": {"$regex": q, "$options": "i"}},
            {"phone": {"$regex": q, "$options": "i"}},
        ]
    docs = await db.users.find(query, {"_id": 0, "password": 0}).sort("created_at", -1).to_list(limit)
    return docs


@api.patch("/admin/users/{uid}")
async def admin_update_user(uid: str, req: AdminUserUpdateReq, user: User = Depends(get_current_user)):
    if not is_admin_role(user.role):
        raise HTTPException(403, "Admin only")
    if uid == user.user_id and (req.banned or req.role not in (None, "admin", "super_admin")):
        raise HTTPException(400, "You cannot ban or demote your own account")
    target = await db.users.find_one({"user_id": uid}, {"_id": 0, "password": 0})
    if not target:
        raise HTTPException(404, "User not found")
    if user.role != "super_admin":
        if is_admin_role(target.get("role", "")):
            raise HTTPException(403, "Only Super Admin can modify an admin account")
        if req.role in ("admin", "super_admin"):
            raise HTTPException(403, "Only Super Admin can grant admin access")
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(400, "Nothing to update")
    await db.users.update_one({"user_id": uid}, {"$set": updates})
    doc = await db.users.find_one({"user_id": uid}, {"_id": 0, "password": 0})
    await log_admin_activity(user, "user_updated", target_type="user", target_id=uid, detail=str(updates))
    return doc


@api.delete("/admin/users/{uid}")
async def admin_delete_user(uid: str, user: User = Depends(get_current_user)):
    if not is_admin_role(user.role):
        raise HTTPException(403, "Admin only")
    if uid == user.user_id:
        raise HTTPException(400, "You cannot delete your own account")
    target = await db.users.find_one({"user_id": uid}, {"_id": 0})
    if not target:
        raise HTTPException(404, "User not found")
    if user.role != "super_admin" and is_admin_role(target.get("role", "")):
        raise HTTPException(403, "Only Super Admin can delete an admin account")
    await db.users.delete_one({"user_id": uid})
    await log_admin_activity(user, "user_deleted", target_type="user", target_id=uid, detail=target.get("email"))
    return {"ok": True}


# ------------------ Admin: Products ------------------
@api.get("/admin/products")
async def admin_list_products(
    q: Optional[str] = None,
    category: Optional[str] = None,
    farmer_id: Optional[str] = None,
    limit: int = 300,
    user: User = Depends(get_current_user),
):
    if not is_admin_role(user.role):
        raise HTTPException(403, "Admin only")
    query: dict = {}
    if category:
        query["category"] = category
    if farmer_id:
        query["farmer_id"] = farmer_id
    if q:
        query["$or"] = [
            {"title": {"$regex": q, "$options": "i"}},
            {"farmer_name": {"$regex": q, "$options": "i"}},
        ]
    # Admin view includes inactive/deactivated listings (unlike the public /products list).
    docs = await db.products.find(query, {"_id": 0}).sort("created_at", -1).to_list(limit)
    return docs


@api.patch("/admin/products/{pid}")
async def admin_update_product(pid: str, req: AdminProductUpdateReq, user: User = Depends(get_current_user)):
    if not is_admin_role(user.role):
        raise HTTPException(403, "Admin only")
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(400, "Nothing to update")
    result = await db.products.update_one({"product_id": pid}, {"$set": updates})
    if result.matched_count == 0:
        raise HTTPException(404, "Product not found")
    doc = await db.products.find_one({"product_id": pid}, {"_id": 0})
    await log_admin_activity(user, "product_updated", target_type="product", target_id=pid, detail=str(updates))
    return doc


@api.delete("/admin/products/{pid}")
async def admin_delete_product(pid: str, user: User = Depends(get_current_user)):
    if not is_admin_role(user.role):
        raise HTTPException(403, "Admin only")
    result = await db.products.delete_one({"product_id": pid})
    if result.deleted_count == 0:
        raise HTTPException(404, "Product not found")
    await log_admin_activity(user, "product_deleted", target_type="product", target_id=pid)
    return {"ok": True}


# ------------------ Admin: Orders ------------------
@api.patch("/admin/orders/{oid}")
async def admin_update_order(oid: str, req: AdminOrderUpdateReq, user: User = Depends(get_current_user)):
    if not is_admin_role(user.role):
        raise HTTPException(403, "Admin only")
    result = await db.orders.update_one({"order_id": oid}, {"$set": {"status": req.status}})
    if result.matched_count == 0:
        raise HTTPException(404, "Order not found")
    doc = await db.orders.find_one({"order_id": oid}, {"_id": 0})
    await log_admin_activity(user, "order_status_updated", target_type="order", target_id=oid, detail=req.status)
    return doc


# ------------------ Admin: Site Settings (platform fee / delivery charge) ------------------
@api.get("/admin/settings")
async def admin_get_settings(user: User = Depends(get_current_user)):
    require_super_admin(user)
    return await get_settings()


@api.put("/admin/settings")
async def admin_update_settings(req: AdminSettingsUpdateReq, user: User = Depends(get_current_user)):
    require_super_admin(user)
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(400, "Nothing to update")
    if "platform_fee_percent" in updates and not (0 <= updates["platform_fee_percent"] <= 100):
        raise HTTPException(400, "Platform fee must be between 0 and 100 percent")
    if "delivery_charge" in updates and updates["delivery_charge"] < 0:
        raise HTTPException(400, "Delivery charge cannot be negative")
    await db.settings.update_one({"settings_id": SETTINGS_DOC_ID}, {"$set": updates}, upsert=True)
    await log_admin_activity(user, "settings_updated", target_type="settings", detail=str(updates))
    return await get_settings()


# ------------------ Admin: Security ------------------
@api.get("/admin/security-logs")
async def admin_security_logs(
    event_type: Optional[str] = None, email: Optional[str] = None, limit: int = 200,
    user: User = Depends(get_current_user),
):
    require_super_admin(user)
    query: dict = {}
    if event_type:
        query["event_type"] = event_type
    if email:
        query["email"] = email
    return await db.security_logs.find(query, {"_id": 0}).sort("created_at", -1).to_list(limit)


@api.get("/admin/locked-accounts")
async def admin_locked_accounts(user: User = Depends(get_current_user)):
    require_super_admin(user)
    now = datetime.now(timezone.utc)
    docs = await db.login_attempts.find({"locked_until": {"$gt": now}}, {"_id": 0}).to_list(200)
    return docs


@api.post("/admin/unlock-account")
async def admin_unlock_account(identifier: str, user: User = Depends(get_current_user)):
    require_super_admin(user)
    result = await db.login_attempts.delete_one({"identifier": identifier})
    if result.deleted_count == 0:
        raise HTTPException(404, "No lockout found for that identifier")
    return {"ok": True}


# ------------------ Admin: Categories ------------------
@api.get("/admin/categories")
async def admin_list_categories(user: User = Depends(get_current_user)):
    if not is_admin_role(user.role):
        raise HTTPException(403, "Admin only")
    docs = await db.categories.find({}, {"_id": 0}).sort("name", 1).to_list(200)
    return docs


@api.post("/admin/categories")
async def admin_create_category(req: CategoryReq, user: User = Depends(get_current_user)):
    if not is_admin_role(user.role):
        raise HTTPException(403, "Admin only")
    if await db.categories.find_one({"id": req.id}):
        raise HTTPException(409, "Category id already exists")
    doc = req.model_dump()
    await db.categories.insert_one(doc)
    doc.pop("_id", None)
    await log_admin_activity(user, "category_created", target_type="category", target_id=req.id)
    return doc


@api.put("/admin/categories/{cid}")
async def admin_update_category(cid: str, req: CategoryReq, user: User = Depends(get_current_user)):
    if not is_admin_role(user.role):
        raise HTTPException(403, "Admin only")
    result = await db.categories.update_one({"id": cid}, {"$set": {"name": req.name, "icon": req.icon}})
    if result.matched_count == 0:
        raise HTTPException(404, "Category not found")
    await log_admin_activity(user, "category_updated", target_type="category", target_id=cid)
    return await db.categories.find_one({"id": cid}, {"_id": 0})


@api.delete("/admin/categories/{cid}")
async def admin_delete_category(cid: str, user: User = Depends(get_current_user)):
    if not is_admin_role(user.role):
        raise HTTPException(403, "Admin only")
    result = await db.categories.delete_one({"id": cid})
    if result.deleted_count == 0:
        raise HTTPException(404, "Category not found")
    await log_admin_activity(user, "category_deleted", target_type="category", target_id=cid)
    return {"ok": True}


# ------------------ Admin: Banners ------------------
@api.get("/banners")
async def public_banners():
    """Public — active banners only, in display order."""
    docs = await db.banners.find({"active": True}, {"_id": 0}).sort("sort_order", 1).to_list(20)
    return docs


@api.get("/admin/banners")
async def admin_list_banners(user: User = Depends(get_current_user)):
    if not is_admin_role(user.role):
        raise HTTPException(403, "Admin only")
    docs = await db.banners.find({}, {"_id": 0}).sort("sort_order", 1).to_list(100)
    return docs


@api.post("/admin/banners")
async def admin_create_banner(req: BannerReq, user: User = Depends(get_current_user)):
    if not is_admin_role(user.role):
        raise HTTPException(403, "Admin only")
    bid = f"banner_{uuid.uuid4().hex[:10]}"
    doc = {"banner_id": bid, **req.model_dump(), "created_at": now_iso()}
    await db.banners.insert_one(doc)
    doc.pop("_id", None)
    await log_admin_activity(user, "banner_created", target_type="banner", target_id=bid)
    return doc


@api.put("/admin/banners/{bid}")
async def admin_update_banner(bid: str, req: BannerReq, user: User = Depends(get_current_user)):
    if not is_admin_role(user.role):
        raise HTTPException(403, "Admin only")
    result = await db.banners.update_one({"banner_id": bid}, {"$set": req.model_dump()})
    if result.matched_count == 0:
        raise HTTPException(404, "Banner not found")
    await log_admin_activity(user, "banner_updated", target_type="banner", target_id=bid)
    return await db.banners.find_one({"banner_id": bid}, {"_id": 0})


@api.delete("/admin/banners/{bid}")
async def admin_delete_banner(bid: str, user: User = Depends(get_current_user)):
    if not is_admin_role(user.role):
        raise HTTPException(403, "Admin only")
    result = await db.banners.delete_one({"banner_id": bid})
    if result.deleted_count == 0:
        raise HTTPException(404, "Banner not found")
    await log_admin_activity(user, "banner_deleted", target_type="banner", target_id=bid)
    return {"ok": True}


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

    async def gen():
        full = ""
        async for chunk in ai_stream_reply(
            db=db, session_id=sid, system=SYSTEM_PROMPT, user_message=req.message
        ):
            full += chunk
            yield chunk
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
    text = await ai_one_shot(
        system=(
            "You are an Indian crop price prediction expert. Given a crop, region and season, "
            "estimate a fair INR/kg or INR/quintal price range with brief 2-line reasoning. "
            "Return: 'Suggested: ₹X-Y per <unit>. Why: ...'"
        ),
        user_message=req.message,
    )
    return {"prediction": text}


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
        await ensure_review_indexes(db)
        await otp_service.ensure_indexes(db)
        await db.categories.create_index("id", unique=True)
        await db.banners.create_index("banner_id", unique=True)
        await db.deliveries.create_index("delivery_id", unique=True)
        await db.deliveries.create_index("order_id")
        await db.deliveries.create_index("assigned_to")
        await db.security_logs.create_index("created_at")
        await db.security_logs.create_index("event_type")
        await db.password_reset_requests.create_index("email")
        await db.password_reset_requests.create_index("created_at", expireAfterSeconds=int(RESET_REQUEST_WINDOW.total_seconds()) * 2)
        await db.admin_activity_logs.create_index("created_at")
        await db.admin_activity_logs.create_index("admin_id")
        # Seed categories from the built-in defaults on first run only, so
        # admin edits/additions afterwards are never overwritten.
        if await db.categories.count_documents({}) == 0:
            await db.categories.insert_many([dict(c) for c in CATEGORIES])
        # One-time bootstrap: if there's no super_admin yet, promote the
        # earliest-created admin account so Super Admin features are usable
        # without needing direct database access.
        if await db.users.count_documents({"role": "super_admin"}) == 0:
            oldest_admin = await db.users.find_one({"role": "admin"}, {"_id": 0, "user_id": 1}, sort=[("created_at", 1)])
            if oldest_admin:
                await db.users.update_one({"user_id": oldest_admin["user_id"]}, {"$set": {"role": "super_admin"}})
                logger.info("Bootstrapped user_id=%s to super_admin (no super_admin existed yet)", oldest_admin["user_id"])
    except Exception as e:
        logger.exception("Index creation failed: %s", e)
