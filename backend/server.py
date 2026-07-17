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
RESET_TOKEN_TTL = timedelta(hours=1)
MIN_PW_LEN = 6


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
    )
    response.set_cookie(
        CSRF_COOKIE, csrf_value,
        httponly=False, secure=True, samesite="none", path="/", max_age=COOKIE_MAX_AGE,
    )
    return csrf_value


def _clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(AUTH_COOKIE, path="/", secure=True, samesite="none")
    response.delete_cookie(CSRF_COOKIE, path="/", secure=True, samesite="none")
    response.delete_cookie(SESSION_COOKIE, path="/", secure=True, samesite="none")


# ------------------ Models ------------------
class User(BaseModel):
    model_config = ConfigDict(extra="ignore")
    user_id: str
    email: str
    name: str
    role: Literal["farmer", "buyer", "exporter", "admin", "delivery_partner"] = "buyer"
    phone: Optional[str] = None
    location: Optional[str] = None
    picture: Optional[str] = None
    verified: bool = False
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


class DeliveryCreate(BaseModel):
    method: Literal["pickup", "local_delivery", "courier", "transport", "seller_delivery"]
    distance_km: Optional[float] = None
    weight_kg: Optional[float] = None
    vehicle_type: Optional[Literal["bike", "mini_truck", "truck"]] = None
    courier_partner: Optional[str] = None
    seller_charge: Optional[float] = None  # only used for method == seller_delivery


class DeliveryStatusUpdate(BaseModel):
    status: Literal["assigned", "picked_up", "out_for_delivery", "delivered", "failed"]
    note: Optional[str] = None


class DeliveryOtpVerify(BaseModel):
    code: str


class DeliveryPartnerCreate(BaseModel):
    name: str
    email: EmailStr
    password: str
    phone: Optional[str] = None


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


class ReviewModerateReq(BaseModel):
    action: Literal["publish", "hide", "delete"]


# ------------------ Helpers ------------------
def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def hash_pw(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()


def verify_pw(pw: str, hashed: str) -> bool:
    return bcrypt.checkpw(pw.encode(), hashed.encode())


def calculate_delivery_charge(
    method: str, *, distance_km: float = 0.0, weight_kg: float = 1.0,
    vehicle_type: str = "bike", seller_charge: Optional[float] = None,
) -> float:
    """Dynamic delivery pricing per method (spec: Delivery Charges System).

    - pickup: always free.
    - seller_delivery: seller sets their own flat charge.
    - local_delivery: base fee + per-km + extra per-kg above a 5kg allowance.
    - courier: flat courier-partner base + per-kg weight charge.
    - transport: per-km * vehicle-type multiplier + per-kg.
    """
    distance_km = max(distance_km or 0.0, 0.0)
    weight_kg = max(weight_kg or 0.0, 0.1)

    if method == "pickup":
        return 0.0
    if method == "seller_delivery":
        return round(max(float(seller_charge or 0), 0), 2)
    if method == "local_delivery":
        base = 15.0
        return round(base + distance_km * 6.0 + max(weight_kg - 5, 0) * 3.0, 2)
    if method == "courier":
        base = 40.0
        return round(base + weight_kg * 12.0, 2)
    if method == "transport":
        multiplier = {"bike": 1.0, "mini_truck": 2.5, "truck": 5.0}.get(vehicle_type, 2.5)
        return round(distance_km * 4.0 * multiplier + weight_kg * 2.0, 2)
    return 0.0


async def _notify(user_id: str, title: str, message: str, ntype: str = "info") -> None:
    """Best-effort in-app notification. Never raises — a notification-write
    failure must not break the order/delivery flow that triggered it."""
    try:
        await db.notifications.insert_one({
            "notification_id": f"notif_{uuid.uuid4().hex[:12]}",
            "user_id": user_id,
            "title": title,
            "message": message,
            "type": ntype,
            "read": False,
            "created_at": now_iso(),
        })
    except Exception:
        logger.exception("Failed to create notification for user=%s", user_id)


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
    return {"user": public_user(doc), "csrf_token": csrf, "access_token": token}


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
    return {"user": public_user(doc), "csrf_token": csrf, "access_token": token}


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
    return {"user": public_user(user), "csrf_token": csrf, "access_token": token}


@api.get("/auth/me")
async def me(response: Response, user: User = Depends(get_current_user), csrf_token: Optional[str] = Cookie(None)):
    # Ensure CSRF cookie exists for any authenticated session (covers legacy logins)
    if not csrf_token:
        new_csrf = secrets.token_urlsafe(32)
        response.set_cookie(
            CSRF_COOKIE, new_csrf,
            httponly=False, secure=True, samesite="none", path="/", max_age=COOKIE_MAX_AGE,
        )
    return user


@api.post("/auth/csrf")
async def issue_csrf(response: Response):
    """Issue (or rotate) a CSRF token. Safe to call before login as well."""
    csrf = secrets.token_urlsafe(32)
    response.set_cookie(
        CSRF_COOKIE, csrf,
        httponly=False, secure=True, samesite="none", path="/", max_age=COOKIE_MAX_AGE,
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
    return {"user": public_user(user), "csrf_token": csrf, "access_token": session_token}


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


# ------------------ Delivery ------------------
@api.post("/orders/{oid}/delivery")
async def create_delivery(oid: str, req: DeliveryCreate, user: User = Depends(get_current_user)):
    """Create the delivery record for an order. Callable by a farmer who owns
    a product in the order, or an admin. One delivery record per order."""
    order = await db.orders.find_one({"order_id": oid}, {"_id": 0})
    if not order:
        raise HTTPException(404, "Order not found")
    if user.role == "farmer":
        pids = [it["product_id"] for it in order["items"]]
        owned = await db.products.count_documents({"product_id": {"$in": pids}, "farmer_id": user.user_id})
        if owned == 0:
            raise HTTPException(403, "Forbidden")
    elif user.role != "admin":
        raise HTTPException(403, "Farmer or admin only")

    if await db.deliveries.find_one({"order_id": oid}):
        raise HTTPException(409, "Delivery already created for this order")

    weight_kg = req.weight_kg or sum(it["qty"] for it in order["items"])
    charge = calculate_delivery_charge(
        req.method, distance_km=req.distance_km or 0.0, weight_kg=weight_kg,
        vehicle_type=req.vehicle_type or "bike", seller_charge=req.seller_charge,
    )
    did = f"del_{uuid.uuid4().hex[:12]}"
    is_pickup = req.method == "pickup"
    otp_code = f"{secrets.randbelow(1_000_000):06d}"
    doc = {
        "delivery_id": did,
        "order_id": oid,
        "buyer_id": order["buyer_id"],
        "method": req.method,
        "distance_km": req.distance_km,
        "weight_kg": weight_kg,
        "vehicle_type": req.vehicle_type,
        "courier_partner": req.courier_partner,
        "charge": charge,
        "status": "delivered" if is_pickup else "assigned",
        "assigned_partner_id": None,
        "otp_code": otp_code,
        "otp_verified": is_pickup,
        "history": [{"status": "delivered" if is_pickup else "assigned", "at": now_iso(), "note": "Delivery created"}],
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    await db.deliveries.insert_one(doc)
    await db.orders.update_one(
        {"order_id": oid},
        {"$set": {"status": "delivered" if is_pickup else "confirmed", "delivery_charge": charge}},
    )
    await _notify(
        order["buyer_id"], "Delivery arranged",
        f"Your order {oid} delivery has been arranged via {req.method.replace('_', ' ')}.",
        "delivery",
    )
    doc.pop("_id", None)
    if user.role != "admin":
        doc.pop("otp_code", None)
    return doc


@api.get("/orders/{oid}/delivery")
async def get_delivery(oid: str, user: User = Depends(get_current_user)):
    d = await db.deliveries.find_one({"order_id": oid}, {"_id": 0})
    if not d:
        raise HTTPException(404, "No delivery record for this order")
    if user.role == "admin" or user.user_id in (d["buyer_id"], d.get("assigned_partner_id")):
        if user.role != "admin":
            d.pop("otp_code", None)
        return d
    if user.role == "farmer":
        order = await db.orders.find_one({"order_id": oid}, {"_id": 0})
        pids = [it["product_id"] for it in (order or {}).get("items", [])]
        if await db.products.count_documents({"product_id": {"$in": pids}, "farmer_id": user.user_id}):
            d.pop("otp_code", None)
            return d
    raise HTTPException(403, "Forbidden")


@api.get("/delivery/my")
async def my_deliveries(user: User = Depends(get_current_user)):
    """The logged-in delivery partner's assigned jobs (or all, for admin)."""
    if user.role not in ("delivery_partner", "admin"):
        raise HTTPException(403, "Delivery partner only")
    q = {} if user.role == "admin" else {"assigned_partner_id": user.user_id}
    docs = await db.deliveries.find(q, {"_id": 0, "otp_code": 0}).sort("created_at", -1).to_list(500)
    return docs


@api.patch("/delivery/{did}/assign")
async def assign_delivery_partner(did: str, partner_id: str, user: User = Depends(get_current_user)):
    if user.role != "admin":
        raise HTTPException(403, "Admin only")
    if not await db.users.find_one({"user_id": partner_id, "role": "delivery_partner"}):
        raise HTTPException(404, "Delivery partner not found")
    r = await db.deliveries.update_one(
        {"delivery_id": did},
        {"$set": {"assigned_partner_id": partner_id, "updated_at": now_iso()}},
    )
    if r.matched_count == 0:
        raise HTTPException(404, "Delivery not found")
    return {"ok": True}


@api.patch("/delivery/{did}/status")
async def update_delivery_status(did: str, req: DeliveryStatusUpdate, user: User = Depends(get_current_user)):
    d = await db.deliveries.find_one({"delivery_id": did})
    if not d:
        raise HTTPException(404, "Delivery not found")
    is_assigned_partner = user.role == "delivery_partner" and d.get("assigned_partner_id") == user.user_id
    if user.role != "admin" and not is_assigned_partner:
        raise HTTPException(403, "Forbidden")
    if req.status == "delivered" and not d.get("otp_verified"):
        raise HTTPException(400, "Delivery OTP must be verified before marking delivered")
    entry = {"status": req.status, "at": now_iso(), "note": req.note}
    await db.deliveries.update_one(
        {"delivery_id": did},
        {"$set": {"status": req.status, "updated_at": now_iso()}, "$push": {"history": entry}},
    )
    order_status = {"picked_up": "shipped", "out_for_delivery": "shipped", "delivered": "delivered"}.get(req.status)
    if order_status:
        await db.orders.update_one({"order_id": d["order_id"]}, {"$set": {"status": order_status}})
    await _notify(
        d["buyer_id"], "Delivery update",
        f"Your order {d['order_id']} is now: {req.status.replace('_', ' ')}.",
        "delivery",
    )
    return {"ok": True, "status": req.status}


@api.post("/delivery/{did}/verify-otp")
async def verify_delivery_otp(did: str, req: DeliveryOtpVerify, user: User = Depends(get_current_user)):
    """Buyer or the assigned delivery partner confirms handover with the OTP
    shown to the buyer — this is the proof-of-delivery step."""
    d = await db.deliveries.find_one({"delivery_id": did})
    if not d:
        raise HTTPException(404, "Delivery not found")
    allowed = user.role == "admin" or user.user_id in (d["buyer_id"], d.get("assigned_partner_id"))
    if not allowed:
        raise HTTPException(403, "Forbidden")
    if d.get("otp_verified"):
        return {"ok": True, "already_verified": True}
    if req.code != d.get("otp_code"):
        raise HTTPException(400, "Incorrect delivery code")
    entry = {"status": "delivered", "at": now_iso(), "note": "OTP verified"}
    await db.deliveries.update_one(
        {"delivery_id": did},
        {"$set": {"otp_verified": True, "status": "delivered", "updated_at": now_iso()}, "$push": {"history": entry}},
    )
    await db.orders.update_one({"order_id": d["order_id"]}, {"$set": {"status": "delivered"}})
    await _notify(d["buyer_id"], "Order delivered", f"Your order {d['order_id']} has been delivered. Thank you!", "delivery")
    return {"ok": True}


@api.post("/delivery/charge-estimate")
async def delivery_charge_estimate(req: DeliveryCreate):
    """Public checkout-time estimate — no order/auth required yet, so the
    buyer can see delivery cost before placing the order."""
    weight_kg = req.weight_kg or 1.0
    charge = calculate_delivery_charge(
        req.method, distance_km=req.distance_km or 0.0, weight_kg=weight_kg,
        vehicle_type=req.vehicle_type or "bike", seller_charge=req.seller_charge,
    )
    return {"method": req.method, "charge": charge}


@api.get("/admin/deliveries")
async def admin_list_deliveries(status: Optional[str] = None, user: User = Depends(get_current_user)):
    if user.role != "admin":
        raise HTTPException(403, "Admin only")
    q: dict = {}
    if status:
        q["status"] = status
    docs = await db.deliveries.find(q, {"_id": 0, "otp_code": 0}).sort("created_at", -1).to_list(1000)
    return docs


@api.post("/admin/delivery-partners")
async def create_delivery_partner(req: DeliveryPartnerCreate, user: User = Depends(get_current_user)):
    """Admin onboards a delivery partner account directly (no public
    self-registration for this role, matching real-world onboarding)."""
    if user.role != "admin":
        raise HTTPException(403, "Admin only")
    if await db.users.find_one({"email": req.email.lower()}):
        raise HTTPException(409, "Email already registered")
    partner_id = f"user_{uuid.uuid4().hex[:12]}"
    doc = {
        "user_id": partner_id,
        "email": req.email.lower(),
        "name": req.name,
        "password": hash_pw(req.password),
        "role": "delivery_partner",
        "phone": req.phone,
        "location": None,
        "picture": None,
        "verified": True,
        "created_at": now_iso(),
    }
    await db.users.insert_one(doc)
    return public_user(doc)


@api.get("/admin/delivery-partners")
async def list_delivery_partners(user: User = Depends(get_current_user)):
    if user.role != "admin":
        raise HTTPException(403, "Admin only")
    docs = await db.users.find({"role": "delivery_partner"}, {"_id": 0, "password_hash": 0}).to_list(500)
    return docs


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
    if user.role != "admin":
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
    if user.role != "admin":
        raise HTTPException(403, "Admin only")
    try:
        result = await svc_moderate_review(db, review_id=rid, action=req.action)
    except ValueError as e:
        raise HTTPException(404 if str(e) == "not_found" else 400, str(e))
    return {"ok": True, "deleted": result is None, "review": result}


@api.get("/orders")
async def list_orders(user: User = Depends(get_current_user)):
    docs: list = []
    if user.role == "admin":
        docs = await db.orders.find({}, {"_id": 0}).sort("created_at", -1).to_list(500)
    elif user.role == "farmer":
        prods = await db.products.find({"farmer_id": user.user_id}, {"_id": 0, "product_id": 1}).to_list(500)
        pids = [p["product_id"] for p in prods]
        docs = await db.orders.find({"items.product_id": {"$in": pids}}, {"_id": 0}).sort("created_at", -1).to_list(500)
    elif user.role == "delivery_partner":
        deliveries = await db.deliveries.find(
            {"assigned_partner_id": user.user_id}, {"_id": 0, "order_id": 1},
        ).to_list(500)
        oids = [d["order_id"] for d in deliveries]
        docs = await db.orders.find({"order_id": {"$in": oids}}, {"_id": 0}).sort("created_at", -1).to_list(500)
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
    except Exception as e:
        logger.exception("Index creation failed: %s", e)
