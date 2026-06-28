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
from pydantic import BaseModel, Field, EmailStr, ConfigDict
from typing import List, Optional, Literal
from datetime import datetime, timezone, timedelta

from emergentintegrations.llm.chat import LlmChat, UserMessage, TextDelta, StreamDone

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]
JWT_SECRET = os.environ["JWT_SECRET"]
EMERGENT_LLM_KEY = os.environ["EMERGENT_LLM_KEY"]
FRONTEND_URL = os.environ.get("FRONTEND_URL", "*")

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
    images: List[str] = []
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
    images: List[str] = []
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
    delivery_address: str
    payment_method: str
    payment_status: Literal["pending", "paid", "failed"] = "pending"
    status: Literal["placed", "confirmed", "shipped", "delivered", "cancelled"] = "placed"
    razorpay_order_id: Optional[str] = None
    created_at: str


class ChatReq(BaseModel):
    message: str
    session_id: Optional[str] = None


class BidReq(BaseModel):
    amount: float


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
    if dt.tzinfo is None:
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
    if expires_at.tzinfo is None:
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
    if organic is not None:
        query["organic"] = organic
    if export_ready is not None:
        query["export_ready"] = export_ready
    if auction is not None:
        query["auction"] = auction
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
    await db.products.delete_one({"product_id": pid})
    return {"ok": True}


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
    total = sum(it.qty * it.price for it in req.items)
    oid = f"ord_{uuid.uuid4().hex[:10]}"
    rzp_id = f"order_mock_{uuid.uuid4().hex[:14]}"
    doc = {
        "order_id": oid,
        "buyer_id": user.user_id,
        "buyer_name": user.name,
        "items": [it.model_dump() for it in req.items],
        "total": total,
        "delivery_address": req.delivery_address,
        "payment_method": req.payment_method,
        "payment_status": "pending",
        "status": "placed",
        "razorpay_order_id": rzp_id,
        "created_at": now_iso(),
    }
    await db.orders.insert_one(doc)
    doc.pop("_id", None)
    return doc


@api.post("/orders/{oid}/pay")
async def mock_pay(oid: str, user: User = Depends(get_current_user)):
    order = await db.orders.find_one({"order_id": oid}, {"_id": 0})
    if not order:
        raise HTTPException(404, "Not found")
    if order["buyer_id"] != user.user_id:
        raise HTTPException(403, "Forbidden")
    payment_id = f"pay_mock_{uuid.uuid4().hex[:14]}"
    await db.orders.update_one(
        {"order_id": oid},
        {"$set": {"payment_status": "paid", "status": "confirmed", "razorpay_payment_id": payment_id}},
    )
    return {"ok": True, "payment_id": payment_id}


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
    except Exception as e:
        logger.exception("Index creation failed: %s", e)
