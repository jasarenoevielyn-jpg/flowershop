from fastapi import FastAPI, APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import Response, HTMLResponse
from fastapi.security import OAuth2PasswordBearer
from fastapi.concurrency import run_in_threadpool
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, EmailStr, Field
from typing import List, Optional, Literal
from datetime import datetime, timedelta, timezone
from pathlib import Path
from math import radians, sin, cos, sqrt, atan2
import os, uuid, logging, base64, bcrypt, jwt, requests

import storage

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

mongo_url = os.environ["MONGO_URL"]
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ["DB_NAME"]]

JWT_SECRET = os.environ["JWT_SECRET"]
JWT_ALGO = os.environ.get("JWT_ALGO", "HS256")
ACCESS_MIN = int(os.environ.get("ACCESS_TOKEN_MINUTES", "1440"))
PAYMONGO_SECRET = os.environ.get("PAYMONGO_SECRET_KEY", "")
ADMIN_SIGNUP_CODE = os.environ.get("ADMIN_SIGNUP_CODE", "")
APP_URL = os.environ.get("APP_URL", "").rstrip("/")
PAYMONGO_BASE = "https://api.paymongo.com/v1"

BINAN = {"lat": 14.3419, "lng": 121.0803}

app = FastAPI(title="Elaya API")
api = APIRouter(prefix="/api")
oauth = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("elaya")

Role = Literal["customer", "flower_owner", "admin"]
DELIVERY_METHODS = ["in_house", "third_party", "pickup"]

# ---------- Models ----------
class RegisterIn(BaseModel):
    name: str
    email: EmailStr
    password: str = Field(min_length=6)
    role: Role = "customer"

class AdminRegisterIn(BaseModel):
    name: str
    email: EmailStr
    password: str = Field(min_length=6)
    admin_code: str

class LoginIn(BaseModel):
    email: EmailStr
    password: str

class UserOut(BaseModel):
    id: str
    name: str
    email: EmailStr
    role: Role
    status: str = "active"
    created_at: str

class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut

class ApplicationIn(BaseModel):
    shop_name: str
    description: str = ""
    business_permit_url: str
    location: str = "Biñan, Laguna"
    lat: Optional[float] = None
    lng: Optional[float] = None
    owner_full_name: str
    contact_number: str
    owner_address: str
    image: Optional[str] = None

class ShopUpdateIn(BaseModel):
    shop_name: Optional[str] = None
    description: Optional[str] = None
    location: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    image: Optional[str] = None
    contact_number: Optional[str] = None
    delivery_methods: Optional[List[str]] = None

class ProductIn(BaseModel):
    name: str
    category: Optional[str] = None
    description: Optional[str] = ""
    image: Optional[str] = None
    images: Optional[List[str]] = None  # multi-angle 360 photos
    price: float
    stock: int = 0
    availability: bool = True
    colors: Optional[List[str]] = None
    flowers_included: Optional[List[str]] = None
    primary_flowers: Optional[List[str]] = None
    number_of_flowers: Optional[int] = None
    wrapping: Optional[str] = None
    ribbon: Optional[str] = None
    style: Optional[str] = None

class OrderItemIn(BaseModel):
    product_id: str
    shop_id: str
    name: str
    image: Optional[str] = None
    unit_price: float
    quantity: int = 1

class OrderIn(BaseModel):
    items: List[OrderItemIn]
    contact_name: str = Field(min_length=1)
    contact_phone: str = Field(min_length=1)
    delivery_method: Literal["in_house", "third_party", "pickup"] = "in_house"
    delivery_address: str = ""
    delivery_lat: Optional[float] = BINAN["lat"]
    delivery_lng: Optional[float] = BINAN["lng"]
    notes: Optional[str] = ""
    payment_method: Literal["cod", "gcash"] = "cod"

class MessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=1000)

class OrderStatusIn(BaseModel):
    status: str

class RiderLocationIn(BaseModel):
    lat: float
    lng: float

class RejectIn(BaseModel):
    reason: str = "Application did not meet requirements."

# ---------- Utils ----------
def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def hash_pw(p: str) -> str:
    return bcrypt.hashpw(p.encode(), bcrypt.gensalt()).decode()

def verify_pw(p: str, h: str) -> bool:
    try:
        return bcrypt.checkpw(p.encode(), h.encode())
    except Exception:
        return False

def make_token(user: dict) -> str:
    now = datetime.now(timezone.utc)
    payload = {"sub": user["id"], "role": user["role"], "iat": now, "exp": now + timedelta(minutes=ACCESS_MIN)}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)

def public_user(u: dict) -> UserOut:
    return UserOut(id=u["id"], name=u["name"], email=u["email"], role=u["role"],
                   status=u.get("status", "active"), created_at=u.get("created_at", ""))

def haversine(lat1, lng1, lat2, lng2) -> float:
    if None in (lat1, lng1, lat2, lng2):
        return 0.0
    R = 6371.0
    dlat = radians(lat2 - lat1)
    dlng = radians(lng2 - lng1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng / 2) ** 2
    return round(R * 2 * atan2(sqrt(a), sqrt(1 - a)), 2)

async def get_current_user(token: str = Depends(oauth)) -> dict:
    err = HTTPException(401, "Invalid or expired token", headers={"WWW-Authenticate": "Bearer"})
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
        uid = payload.get("sub")
        if not uid:
            raise err
        user = await db.users.find_one({"id": uid}, {"_id": 0})
        if not user or user.get("status") != "active":
            raise err
        return user
    except jwt.PyJWTError:
        raise err

def require(*roles: str):
    async def dep(u: dict = Depends(get_current_user)) -> dict:
        if u["role"] not in roles:
            raise HTTPException(403, "Insufficient role")
        return u
    return dep

async def approved_shop(u: dict) -> dict:
    shop = await db.shops.find_one({"owner_id": u["id"]}, {"_id": 0})
    if not shop:
        raise HTTPException(400, "No shop application found. Please submit your shop application.")
    if shop.get("status") != "approved":
        raise HTTPException(403, "Your shop is not approved yet.")
    return shop

async def notify(user_id: str, title: str, body: str, order_id: Optional[str] = None, kind: str = "info"):
    await db.notifications.insert_one({
        "id": str(uuid.uuid4()), "user_id": user_id, "title": title, "body": body,
        "order_id": order_id, "kind": kind, "read": False, "created_at": now_iso(),
    })

# ---------- Storage / uploads ----------
@api.post("/upload")
async def upload_file(file: UploadFile = File(...), u=Depends(get_current_user)):
    data = await file.read()
    ext = (file.filename or "file").split(".")[-1].lower()[:8]
    path = f"{storage.APP_NAME}/uploads/{u['id']}/{uuid.uuid4().hex}.{ext}"
    ct = file.content_type or "application/octet-stream"
    await run_in_threadpool(storage.put_object, path, data, ct)
    await db.uploads.insert_one({"id": str(uuid.uuid4()), "owner_id": u["id"], "path": path,
                                 "filename": file.filename, "content_type": ct, "created_at": now_iso()})
    return {"path": path, "url": f"/api/files/{path}", "content_type": ct}

@api.get("/files/{path:path}")
async def get_file(path: str, token: Optional[str] = None):
    rec = await db.uploads.find_one({"path": path}, {"_id": 0})
    if not rec:
        raise HTTPException(404, "File not found")
    content, ct = await run_in_threadpool(storage.get_object, path)
    return Response(content=content, media_type=ct, headers={"Cache-Control": "public, max-age=86400"})

# ---------- Auth ----------
@api.post("/auth/register", response_model=TokenOut)
async def register(data: RegisterIn):
    if data.role == "admin":
        raise HTTPException(400, "Cannot self-register as admin")
    email = data.email.lower()
    if await db.users.find_one({"email": email}):
        raise HTTPException(409, "Email already registered")
    uid = str(uuid.uuid4())
    user = {"id": uid, "name": data.name, "email": email, "password_hash": hash_pw(data.password),
            "role": data.role, "status": "active", "created_at": now_iso()}
    await db.users.insert_one(user)
    return TokenOut(access_token=make_token(user), user=public_user(user))

@api.post("/auth/register-admin", response_model=TokenOut)
async def register_admin(data: AdminRegisterIn):
    if not ADMIN_SIGNUP_CODE:
        raise HTTPException(500, "Admin registration is not configured")
    if data.admin_code.strip() != ADMIN_SIGNUP_CODE:
        raise HTTPException(403, "Invalid admin access code")
    email = data.email.lower()
    if await db.users.find_one({"email": email}):
        raise HTTPException(409, "Email already registered")
    uid = str(uuid.uuid4())
    user = {"id": uid, "name": data.name, "email": email, "password_hash": hash_pw(data.password),
            "role": "admin", "status": "active", "created_at": now_iso()}
    await db.users.insert_one(user)
    return TokenOut(access_token=make_token(user), user=public_user(user))

@api.post("/auth/login", response_model=TokenOut)
async def login(data: LoginIn):
    user = await db.users.find_one({"email": data.email.lower()})
    if not user or not verify_pw(data.password, user["password_hash"]):
        raise HTTPException(401, "Invalid email or password")
    if user.get("status") != "active":
        raise HTTPException(403, "Account disabled")
    return TokenOut(access_token=make_token(user), user=public_user(user))

@api.get("/auth/me", response_model=UserOut)
async def me(u=Depends(get_current_user)):
    return public_user(u)

# ---------- Owner: shop application ----------
@api.get("/owner/application")
async def get_application(u=Depends(require("flower_owner"))):
    shop = await db.shops.find_one({"owner_id": u["id"]}, {"_id": 0})
    if not shop:
        return {"status": "none"}
    shop["product_count"] = await db.products.count_documents({"shop_id": shop["id"], "status": "active"})
    return shop

@api.post("/owner/application")
async def submit_application(data: ApplicationIn, u=Depends(require("flower_owner"))):
    existing = await db.shops.find_one({"owner_id": u["id"]})
    doc = {
        "shop_name": data.shop_name, "description": data.description,
        "business_permit_url": data.business_permit_url,
        "location": data.location, "lat": data.lat or BINAN["lat"], "lng": data.lng or BINAN["lng"],
        "owner_full_name": data.owner_full_name, "contact_number": data.contact_number,
        "owner_address": data.owner_address,
        "image": data.image or "https://images.unsplash.com/photo-1771856558087-80f35365c3bb?w=800",
        "status": "pending", "reject_reason": None, "updated_at": now_iso(),
    }
    if existing:
        if existing.get("status") == "approved":
            raise HTTPException(409, "Shop already approved")
        await db.shops.update_one({"owner_id": u["id"]}, {"$set": doc})
        shop = await db.shops.find_one({"owner_id": u["id"]}, {"_id": 0})
    else:
        doc.update({"id": str(uuid.uuid4()), "owner_id": u["id"],
                    "delivery_methods": DELIVERY_METHODS[:], "created_at": now_iso()})
        await db.shops.insert_one(doc)
        shop = {k: v for k, v in doc.items() if k != "_id"}
    admins = await db.users.find({"role": "admin"}, {"_id": 0, "id": 1}).to_list(50)
    for a in admins:
        await notify(a["id"], "New shop application", f"{data.shop_name} submitted an application for review.", kind="application")
    return shop

@api.get("/shops/mine")
async def my_shop(u=Depends(require("flower_owner"))):
    shop = await db.shops.find_one({"owner_id": u["id"]}, {"_id": 0})
    if not shop:
        raise HTTPException(404, "No shop")
    return shop

@api.put("/shops/mine")
async def update_my_shop(data: ShopUpdateIn, u=Depends(require("flower_owner"))):
    shop = await approved_shop(u)
    upd = {k: v for k, v in data.model_dump().items() if v is not None}
    if "delivery_methods" in upd:
        upd["delivery_methods"] = [m for m in upd["delivery_methods"] if m in DELIVERY_METHODS] or ["pickup"]
    await db.shops.update_one({"id": shop["id"]}, {"$set": upd})
    return await db.shops.find_one({"id": shop["id"]}, {"_id": 0})

# ---------- Shops (customer) ----------
@api.get("/shops")
async def list_shops(lat: Optional[float] = None, lng: Optional[float] = None):
    shops = await db.shops.find({"status": "approved"}, {"_id": 0}).to_list(500)
    clat = lat if lat is not None else BINAN["lat"]
    clng = lng if lng is not None else BINAN["lng"]
    for s in shops:
        s["product_count"] = await db.products.count_documents({"shop_id": s["id"], "status": "active"})
        s["distance_km"] = haversine(clat, clng, s.get("lat"), s.get("lng"))
    shops.sort(key=lambda s: s["distance_km"])
    return shops

@api.get("/shops/{sid}")
async def shop_detail(sid: str):
    s = await db.shops.find_one({"id": sid, "status": "approved"}, {"_id": 0})
    if not s:
        raise HTTPException(404, "Shop not found")
    s["product_count"] = await db.products.count_documents({"shop_id": sid, "status": "active"})
    return s

# ---------- Products ----------
@api.get("/products")
async def list_products(product_type: Optional[str] = None, shop_id: Optional[str] = None):
    q = {"status": "active"}
    if shop_id:
        q["shop_id"] = shop_id
    return await db.products.find(q, {"_id": 0}).sort("created_at", -1).to_list(1000)

@api.get("/products/{pid}")
async def get_product(pid: str):
    p = await db.products.find_one({"id": pid}, {"_id": 0})
    if not p:
        raise HTTPException(404, "Not found")
    shop = await db.shops.find_one({"id": p["shop_id"]}, {"_id": 0})
    p["shop"] = {"id": shop["id"], "shop_name": shop["shop_name"], "location": shop.get("location"),
                 "delivery_methods": shop.get("delivery_methods", DELIVERY_METHODS)} if shop else None
    return p

@api.get("/owner/products")
async def my_products(u=Depends(require("flower_owner"))):
    return await db.products.find({"owner_id": u["id"], "status": "active"}, {"_id": 0}).sort("created_at", -1).to_list(1000)

@api.post("/owner/products")
async def add_product(data: ProductIn, u=Depends(require("flower_owner"))):
    shop = await approved_shop(u)
    imgs = data.images or ([data.image] if data.image else [])
    body = data.model_dump()
    body.update({"image": imgs[0] if imgs else data.image, "images": imgs})
    p = {"id": str(uuid.uuid4()), "shop_id": shop["id"], "owner_id": u["id"], "product_type": "bouquet",
         **body, "status": "active", "created_at": now_iso()}
    await db.products.insert_one(p)
    p.pop("_id", None)
    return p

@api.put("/owner/products/{pid}")
async def update_product(pid: str, data: ProductIn, u=Depends(require("flower_owner"))):
    p = await db.products.find_one({"id": pid})
    if not p:
        raise HTTPException(404, "Not found")
    if p["owner_id"] != u["id"]:
        raise HTTPException(403, "Not your product")
    imgs = data.images or ([data.image] if data.image else [])
    upd = {**data.model_dump(), "image": imgs[0] if imgs else data.image, "images": imgs}
    await db.products.update_one({"id": pid}, {"$set": upd})
    return await db.products.find_one({"id": pid}, {"_id": 0})

@api.delete("/owner/products/{pid}")
async def delete_product(pid: str, u=Depends(require("flower_owner"))):
    p = await db.products.find_one({"id": pid})
    if not p or p["owner_id"] != u["id"]:
        raise HTTPException(403, "Not your product")
    await db.products.update_one({"id": pid}, {"$set": {"status": "deleted", "deleted_at": now_iso()}})
    return {"ok": True}

# ---------- Orders ----------
def status_flow(method: str) -> List[str]:
    if method == "pickup":
        return ["pending", "confirmed", "preparing", "ready_for_pickup", "completed"]
    if method == "third_party":
        return ["pending", "confirmed", "preparing", "handed_to_courier", "out_for_delivery", "completed"]
    return ["pending", "confirmed", "preparing", "ready_for_delivery", "out_for_delivery", "completed"]

@api.post("/orders")
async def create_order(data: OrderIn, u=Depends(require("customer"))):
    if not data.items:
        raise HTTPException(400, "Cart is empty")
    total = sum(i.unit_price * i.quantity for i in data.items)
    shop_ids = list({i.shop_id for i in data.items})
    oid = str(uuid.uuid4())
    order = {
        "id": oid, "order_no": f"ELY-{oid[:6].upper()}",
        "customer_id": u["id"], "customer_name": u["name"],
        "contact_name": data.contact_name.strip(), "contact_phone": data.contact_phone.strip(),
        "items": [i.model_dump() for i in data.items], "shop_ids": shop_ids,
        "delivery_method": data.delivery_method,
        "delivery_address": data.delivery_address, "delivery_lat": data.delivery_lat, "delivery_lng": data.delivery_lng,
        "notes": data.notes, "payment_method": data.payment_method,
        "payment_status": "unpaid", "payment_ref": None,
        "status": "pending", "status_flow": status_flow(data.delivery_method),
        "total": total, "created_at": now_iso(), "updated_at": now_iso(),
        "rider_lat": BINAN["lat"], "rider_lng": BINAN["lng"], "rider_name": None,
    }
    order["out_for_delivery_at"] = None
    order["rider_manual"] = False
    await db.orders.insert_one(order)
    # Best-effort stock decrement so low-stock alerts stay realistic
    for i in data.items:
        await db.products.update_one({"id": i.product_id}, {"$inc": {"stock": -i.quantity}})
    order.pop("_id", None)
    return order

@api.get("/orders/mine")
async def my_orders(u=Depends(require("customer"))):
    return await db.orders.find({"customer_id": u["id"]}, {"_id": 0}).sort("created_at", -1).to_list(500)

@api.get("/orders/{oid}")
async def order_detail(oid: str, u=Depends(get_current_user)):
    o = await db.orders.find_one({"id": oid}, {"_id": 0})
    if not o:
        raise HTTPException(404, "Not found")
    if u["role"] == "customer" and o["customer_id"] != u["id"]:
        raise HTTPException(403)
    if u["role"] == "flower_owner":
        shop = await db.shops.find_one({"owner_id": u["id"]})
        if not shop or shop["id"] not in o["shop_ids"]:
            raise HTTPException(403)
    return o

@api.get("/owner/orders")
async def owner_orders(u=Depends(require("flower_owner"))):
    shop = await db.shops.find_one({"owner_id": u["id"]})
    if not shop:
        return []
    return await db.orders.find({"shop_ids": shop["id"]}, {"_id": 0}).sort("created_at", -1).to_list(500)

@api.patch("/owner/orders/{oid}/status")
async def update_status(oid: str, data: OrderStatusIn, u=Depends(require("flower_owner"))):
    shop = await approved_shop(u)
    o = await db.orders.find_one({"id": oid})
    if not o or shop["id"] not in o["shop_ids"]:
        raise HTTPException(403)
    flow = o.get("status_flow") or status_flow(o.get("delivery_method", "in_house"))
    if data.status not in flow + ["cancelled"]:
        raise HTTPException(400, "Invalid status")
    extra = {}
    if data.status == "out_for_delivery":
        extra["out_for_delivery_at"] = now_iso()
    await db.orders.update_one({"id": oid}, {"$set": {"status": data.status, "updated_at": now_iso(), **extra}})
    await notify(o["customer_id"], "Order update", f"Your order {o['order_no']} is now {data.status.replace('_', ' ')}.",
                 order_id=oid, kind="order")
    return await db.orders.find_one({"id": oid}, {"_id": 0})

@api.patch("/owner/orders/{oid}/rider")
async def update_rider(oid: str, data: RiderLocationIn, u=Depends(require("flower_owner"))):
    shop = await approved_shop(u)
    o = await db.orders.find_one({"id": oid})
    if not o or shop["id"] not in o["shop_ids"]:
        raise HTTPException(403)
    await db.orders.update_one({"id": oid}, {"$set": {"rider_lat": data.lat, "rider_lng": data.lng, "rider_name": u["name"], "rider_manual": True}})
    return {"ok": True}

@api.get("/orders/{oid}/tracking")
async def order_tracking(oid: str):
    """Public live-tracking pin. Order id is an unguessable UUID.
    For in-house orders that are out for delivery, the rider position is
    interpolated from the shop toward the customer over ~8 minutes so the
    customer sees the pin move. A real GPS share by the owner overrides this."""
    o = await db.orders.find_one({"id": oid}, {"_id": 0})
    if not o:
        raise HTTPException(404, "Order not found")
    dest_lat = o.get("delivery_lat") or BINAN["lat"]
    dest_lng = o.get("delivery_lng") or BINAN["lng"]
    start_lat, start_lng = BINAN["lat"], BINAN["lng"]
    if o.get("shop_ids"):
        shop = await db.shops.find_one({"id": o["shop_ids"][0]}, {"_id": 0})
        if shop:
            start_lat = shop.get("lat") or start_lat
            start_lng = shop.get("lng") or start_lng
    method = o.get("delivery_method")
    status = o.get("status")
    base = {"dest_lat": dest_lat, "dest_lng": dest_lng, "start_lat": start_lat,
            "start_lng": start_lng, "status": status, "method": method}
    if method == "pickup":
        return {**base, "lat": start_lat, "lng": start_lng, "moving": False, "progress": 0, "eta_min": 0}
    if o.get("rider_manual") and o.get("rider_lat") is not None:
        return {**base, "lat": o["rider_lat"], "lng": o["rider_lng"], "moving": status == "out_for_delivery", "progress": None, "eta_min": 0}
    progress = 0.0
    if status == "completed":
        progress = 1.0
    elif status == "out_for_delivery" and o.get("out_for_delivery_at"):
        try:
            t0 = datetime.fromisoformat(o["out_for_delivery_at"])
            elapsed = (datetime.now(timezone.utc) - t0).total_seconds()
            progress = max(0.0, min(1.0, elapsed / 480.0))
        except Exception:
            progress = 0.0
    lat = start_lat + (dest_lat - start_lat) * progress
    lng = start_lng + (dest_lng - start_lng) * progress
    await db.orders.update_one({"id": oid}, {"$set": {"rider_lat": lat, "rider_lng": lng}})
    moving = status == "out_for_delivery" and progress < 1.0
    eta_min = max(1, round((1 - progress) * 8)) if moving else 0
    return {**base, "lat": lat, "lng": lng, "moving": moving, "progress": round(progress, 3), "eta_min": eta_min}

# ---------- Order access helper, completion & chat ----------
async def order_for_user(oid: str, u: dict) -> dict:
    """Return the order if this user may view it (customer owner, shop owner in
    order, or admin), else raise. Shared by chat + completion routes."""
    o = await db.orders.find_one({"id": oid})
    if not o:
        raise HTTPException(404, "Order not found")
    if u["role"] == "customer" and o["customer_id"] != u["id"]:
        raise HTTPException(403)
    if u["role"] == "flower_owner":
        shop = await db.shops.find_one({"owner_id": u["id"]})
        if not shop or shop["id"] not in o["shop_ids"]:
            raise HTTPException(403)
    return o

@api.post("/orders/{oid}/complete")
async def complete_order(oid: str, u=Depends(require("customer"))):
    """Customer confirms they received the order. Marks it completed and
    notifies the shop owner(s). COD is settled as paid on receipt."""
    o = await db.orders.find_one({"id": oid})
    if not o or o["customer_id"] != u["id"]:
        raise HTTPException(404, "Order not found")
    if o.get("status") == "completed":
        return {"ok": True, "status": "completed"}
    upd = {"status": "completed", "completed_by_customer": True, "completed_at": now_iso(), "updated_at": now_iso()}
    if o.get("payment_method") == "cod":
        upd["payment_status"] = "paid"
    await db.orders.update_one({"id": oid}, {"$set": upd})
    for sid in o["shop_ids"]:
        shop = await db.shops.find_one({"id": sid}, {"_id": 0})
        if shop:
            await notify(shop["owner_id"], "Order received ✅",
                         f"{u['name']} confirmed receipt of order {o['order_no']}.", order_id=oid, kind="order")
    return {"ok": True, "status": "completed"}

@api.get("/orders/{oid}/messages")
async def list_messages(oid: str, u=Depends(get_current_user)):
    await order_for_user(oid, u)
    return await db.messages.find({"order_id": oid}, {"_id": 0}).sort("created_at", 1).to_list(2000)

@api.post("/orders/{oid}/messages")
async def send_message(oid: str, data: MessageIn, u=Depends(get_current_user)):
    o = await order_for_user(oid, u)
    text = data.text.strip()
    msg = {"id": str(uuid.uuid4()), "order_id": oid, "sender_id": u["id"], "sender_name": u["name"],
           "sender_role": u["role"], "text": text, "created_at": now_iso()}
    await db.messages.insert_one(msg)
    msg.pop("_id", None)
    preview = text[:60]
    if u["role"] == "customer":
        for sid in o["shop_ids"]:
            shop = await db.shops.find_one({"id": sid}, {"_id": 0})
            if shop:
                await notify(shop["owner_id"], f"💬 {u['name']}",
                             f"Order {o['order_no']}: {preview}", order_id=oid, kind="chat")
    else:
        await notify(o["customer_id"], "💬 Message from the shop",
                     f"Order {o['order_no']}: {preview}", order_id=oid, kind="chat")
    return msg


# ---------- Payments (PayMongo GCash + COD) ----------
def paymongo_headers():
    token = base64.b64encode(f"{PAYMONGO_SECRET}:".encode()).decode()
    return {"Authorization": f"Basic {token}", "Content-Type": "application/json"}

def _pm_create_gcash(amount_centavos: int, oid: str, order_no: str, return_url: str) -> dict:
    pi = requests.post(f"{PAYMONGO_BASE}/payment_intents", headers=paymongo_headers(), json={"data": {"attributes": {
        "amount": amount_centavos, "currency": "PHP", "payment_method_allowed": ["gcash"],
        "capture_type": "automatic", "description": f"Elaya order {order_no}",
        "metadata": {"order_id": oid, "order_no": order_no}}}}, timeout=30)
    pi.raise_for_status()
    intent = pi.json()["data"]
    intent_id = intent["id"]
    pm = requests.post(f"{PAYMONGO_BASE}/payment_methods", headers=paymongo_headers(), json={"data": {"attributes": {
        "type": "gcash"}}}, timeout=30)
    pm.raise_for_status()
    method_id = pm.json()["data"]["id"]
    at = requests.post(f"{PAYMONGO_BASE}/payment_intents/{intent_id}/attach", headers=paymongo_headers(),
                       json={"data": {"attributes": {"payment_method": method_id, "return_url": return_url}}}, timeout=30)
    at.raise_for_status()
    attrs = at.json()["data"]["attributes"]
    redirect = (attrs.get("next_action") or {}).get("redirect", {}).get("url")
    return {"intent_id": intent_id, "redirect_url": redirect}

def _pm_get_intent(intent_id: str) -> dict:
    r = requests.get(f"{PAYMONGO_BASE}/payment_intents/{intent_id}", headers=paymongo_headers(), timeout=30)
    r.raise_for_status()
    return r.json()["data"]

@api.post("/orders/{oid}/pay/gcash")
async def pay_gcash(oid: str, u=Depends(require("customer"))):
    o = await db.orders.find_one({"id": oid})
    if not o or o["customer_id"] != u["id"]:
        raise HTTPException(404, "Order not found")
    if o.get("payment_status") == "paid":
        return {"already_paid": True}
    if not PAYMONGO_SECRET:
        raise HTTPException(500, "Payment gateway not configured")
    amount = max(10000, int(round(o["total"] * 100)))
    return_url = f"{APP_URL}/api/payments/return?order_id={oid}"
    try:
        res = await run_in_threadpool(_pm_create_gcash, amount, oid, o["order_no"], return_url)
    except requests.HTTPError as e:
        logger.error("PayMongo error: %s", getattr(e.response, "text", e))
        raise HTTPException(502, "Unable to start GCash payment")
    if not res.get("redirect_url"):
        raise HTTPException(502, "GCash checkout unavailable")
    await db.orders.update_one({"id": oid}, {"$set": {"payment_status": "pending", "paymongo_intent_id": res["intent_id"], "updated_at": now_iso()}})
    return {"redirect_url": res["redirect_url"], "intent_id": res["intent_id"]}

@api.get("/orders/{oid}/payment-status")
async def payment_status(oid: str, u=Depends(get_current_user)):
    o = await db.orders.find_one({"id": oid}, {"_id": 0})
    if not o:
        raise HTTPException(404, "Order not found")
    # Reconcile with PayMongo (webhook-less flow)
    if o.get("payment_status") != "paid" and o.get("paymongo_intent_id") and PAYMONGO_SECRET:
        try:
            intent = await run_in_threadpool(_pm_get_intent, o["paymongo_intent_id"])
            st = intent["attributes"]["status"]
            if st == "succeeded":
                payments = intent["attributes"].get("payments") or []
                ref = payments[0]["id"] if payments else o["paymongo_intent_id"]
                await db.orders.update_one({"id": oid}, {"$set": {"payment_status": "paid", "payment_ref": ref, "paid_at": now_iso(), "updated_at": now_iso()}})
                o["payment_status"] = "paid"
                o["payment_ref"] = ref
                for sid in o["shop_ids"]:
                    shop = await db.shops.find_one({"id": sid}, {"_id": 0})
                    if shop:
                        await notify(shop["owner_id"], "Payment received 🎉",
                                     f"Order {o['order_no']} has been paid via GCash (Ref: {ref}).", order_id=oid, kind="payment")
        except requests.HTTPError:
            pass
    return {"payment_status": o.get("payment_status"), "payment_ref": o.get("payment_ref"), "status": o.get("status")}

@api.post("/orders/{oid}/pay/cod")
async def pay_cod(oid: str, u=Depends(require("customer"))):
    o = await db.orders.find_one({"id": oid})
    if not o or o["customer_id"] != u["id"]:
        raise HTTPException(404, "Order not found")
    await db.orders.update_one({"id": oid}, {"$set": {"payment_method": "cod", "payment_status": "cod_pending", "updated_at": now_iso()}})
    for sid in o["shop_ids"]:
        shop = await db.shops.find_one({"id": sid}, {"_id": 0})
        if shop:
            await notify(shop["owner_id"], "New COD order",
                         f"Order {o['order_no']} placed (Cash on Delivery).", order_id=oid, kind="order")
    return {"ok": True, "payment_status": "cod_pending"}

@api.get("/payments/return", response_class=HTMLResponse)
async def payments_return(order_id: str):
    return """<!doctype html><html><head><meta name='viewport' content='width=device-width,initial-scale=1'>
<style>body{font-family:-apple-system,Segoe UI,Roboto,sans-serif;background:#FFF5F7;color:#2B1E22;display:flex;
align-items:center;justify-content:center;height:100vh;margin:0;text-align:center;padding:24px}
.c{max-width:320px}.e{font-size:52px}h1{font-size:22px;margin:12px 0 6px}p{color:#8A7178}</style></head>
<body><div class='c'><div class='e'>🌸</div><h1>Payment complete</h1>
<p>You can now return to Elaya. Your order will update automatically.</p></div></body></html>"""

# ---------- Notifications ----------
@api.get("/notifications")
async def list_notifications(u=Depends(get_current_user)):
    return await db.notifications.find({"user_id": u["id"]}, {"_id": 0}).sort("created_at", -1).to_list(100)

@api.post("/notifications/{nid}/read")
async def read_notification(nid: str, u=Depends(get_current_user)):
    await db.notifications.update_one({"id": nid, "user_id": u["id"]}, {"$set": {"read": True}})
    return {"ok": True}

@api.post("/notifications/read-all")
async def read_all(u=Depends(get_current_user)):
    await db.notifications.update_many({"user_id": u["id"]}, {"$set": {"read": True}})
    return {"ok": True}

# ---------- Reviews & Ratings ----------
class ReviewIn(BaseModel):
    product_id: str
    rating: int = Field(ge=1, le=5)
    comment: str = ""

async def _recompute_product_rating(pid: str):
    revs = await db.reviews.find({"product_id": pid}, {"_id": 0, "rating": 1}).to_list(10000)
    count = len(revs)
    avg = round(sum(r["rating"] for r in revs) / count, 2) if count else 0
    await db.products.update_one({"id": pid}, {"$set": {"rating_avg": avg, "rating_count": count}})

async def _recompute_shop_rating(sid: str):
    revs = await db.reviews.find({"shop_id": sid}, {"_id": 0, "rating": 1}).to_list(10000)
    count = len(revs)
    avg = round(sum(r["rating"] for r in revs) / count, 2) if count else 0
    await db.shops.update_one({"id": sid}, {"$set": {"rating_avg": avg, "rating_count": count}})

async def _has_ordered(user_id: str, product_id: str) -> bool:
    o = await db.orders.find_one({"customer_id": user_id, "items.product_id": product_id})
    return o is not None

@api.get("/products/{pid}/reviews")
async def product_reviews(pid: str):
    return await db.reviews.find({"product_id": pid}, {"_id": 0}).sort("created_at", -1).to_list(500)

@api.get("/shops/{sid}/reviews")
async def shop_reviews(sid: str):
    return await db.reviews.find({"shop_id": sid}, {"_id": 0}).sort("created_at", -1).to_list(500)

@api.get("/reviews/eligibility")
async def review_eligibility(product_id: str, u=Depends(require("customer"))):
    ordered = await _has_ordered(u["id"], product_id)
    existing = await db.reviews.find_one({"user_id": u["id"], "product_id": product_id}, {"_id": 0})
    return {"can_review": ordered, "already_reviewed": bool(existing),
            "my_review": existing}

@api.post("/reviews")
async def create_review(data: ReviewIn, u=Depends(require("customer"))):
    p = await db.products.find_one({"id": data.product_id}, {"_id": 0})
    if not p:
        raise HTTPException(404, "Product not found")
    if not await _has_ordered(u["id"], data.product_id):
        raise HTTPException(403, "You can only review bouquets you have ordered.")
    sid = p["shop_id"]
    doc = {"user_id": u["id"], "user_name": u["name"], "product_id": data.product_id,
           "product_name": p["name"], "shop_id": sid, "rating": data.rating,
           "comment": data.comment.strip(), "created_at": now_iso()}
    existing = await db.reviews.find_one({"user_id": u["id"], "product_id": data.product_id})
    if existing:
        await db.reviews.update_one({"id": existing["id"]}, {"$set": {**doc, "updated_at": now_iso()}})
    else:
        doc["id"] = str(uuid.uuid4())
        await db.reviews.insert_one(doc)
        owner = await db.shops.find_one({"id": sid}, {"_id": 0})
        if owner:
            await notify(owner["owner_id"], "New review ⭐", f"{u['name']} rated \"{p['name']}\" {data.rating}/5.", kind="review")
    await _recompute_product_rating(data.product_id)
    await _recompute_shop_rating(sid)
    return {"ok": True}

# ---------- Favorites ----------
@api.post("/favorites/{pid}")
async def add_fav(pid: str, u=Depends(require("customer"))):
    await db.favorites.update_one({"user_id": u["id"], "product_id": pid},
                                  {"$setOnInsert": {"user_id": u["id"], "product_id": pid, "created_at": now_iso()}}, upsert=True)
    return {"ok": True}

@api.delete("/favorites/{pid}")
async def rm_fav(pid: str, u=Depends(require("customer"))):
    await db.favorites.delete_one({"user_id": u["id"], "product_id": pid})
    return {"ok": True}

@api.get("/favorites")
async def list_favs(u=Depends(require("customer"))):
    favs = await db.favorites.find({"user_id": u["id"]}, {"_id": 0}).to_list(1000)
    ids = [f["product_id"] for f in favs]
    return await db.products.find({"id": {"$in": ids}, "status": "active"}, {"_id": 0}).to_list(1000)

# ---------- Admin ----------
@api.get("/admin/overview")
async def admin_overview(u=Depends(require("admin"))):
    revenue_docs = await db.orders.find({"status": "completed"}, {"_id": 0, "total": 1}).to_list(10000)
    return {
        "total_customers": await db.users.count_documents({"role": "customer"}),
        "total_owners": await db.users.count_documents({"role": "flower_owner"}),
        "total_shops": await db.shops.count_documents({}),
        "shops_pending": await db.shops.count_documents({"status": "pending"}),
        "shops_approved": await db.shops.count_documents({"status": "approved"}),
        "shops_rejected": await db.shops.count_documents({"status": "rejected"}),
        "total_products": await db.products.count_documents({"status": "active"}),
        "total_orders": await db.orders.count_documents({}),
        "pending_orders": await db.orders.count_documents({"status": "pending"}),
        "completed_orders": await db.orders.count_documents({"status": "completed"}),
        "revenue": sum(o.get("total", 0) for o in revenue_docs),
    }

@api.get("/admin/shop-owners")
async def admin_shop_owners(status: Optional[str] = None, u=Depends(require("admin"))):
    q = {} if not status else {"status": status}
    shops = await db.shops.find(q, {"_id": 0}).sort("created_at", -1).to_list(1000)
    for s in shops:
        owner = await db.users.find_one({"id": s["owner_id"]}, {"_id": 0, "password_hash": 0})
        s["owner_email"] = owner["email"] if owner else None
        s["product_count"] = await db.products.count_documents({"shop_id": s["id"], "status": "active"})
    return shops

@api.patch("/admin/shop-owners/{sid}/approve")
async def approve_shop(sid: str, u=Depends(require("admin"))):
    s = await db.shops.find_one({"id": sid})
    if not s:
        raise HTTPException(404, "Not found")
    await db.shops.update_one({"id": sid}, {"$set": {"status": "approved", "reject_reason": None, "reviewed_at": now_iso()}})
    await notify(s["owner_id"], "Shop approved ✅", f"Congratulations! {s['shop_name']} is now approved. You can start selling.", kind="application")
    return {"ok": True}

@api.patch("/admin/shop-owners/{sid}/reject")
async def reject_shop(sid: str, data: RejectIn, u=Depends(require("admin"))):
    s = await db.shops.find_one({"id": sid})
    if not s:
        raise HTTPException(404, "Not found")
    await db.shops.update_one({"id": sid}, {"$set": {"status": "rejected", "reject_reason": data.reason, "reviewed_at": now_iso()}})
    await notify(s["owner_id"], "Application rejected", f"{s['shop_name']}: {data.reason} You may re-apply.", kind="application")
    return {"ok": True}

@api.get("/admin/users")
async def admin_users(u=Depends(require("admin"))):
    return await db.users.find({}, {"_id": 0, "password_hash": 0}).sort("created_at", -1).to_list(1000)

@api.patch("/admin/users/{uid}/status")
async def admin_user_status(uid: str, new_status: str, u=Depends(require("admin"))):
    await db.users.update_one({"id": uid}, {"$set": {"status": new_status}})
    return {"ok": True}

@api.get("/admin/orders")
async def admin_orders(u=Depends(require("admin"))):
    return await db.orders.find({}, {"_id": 0}).sort("created_at", -1).to_list(1000)

@api.get("/")
async def root():
    return {"message": "Elaya API"}

app.include_router(api)
app.add_middleware(CORSMiddleware, allow_credentials=True, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.on_event("startup")
async def on_start():
    try:
        await run_in_threadpool(storage.init_storage)
    except Exception as e:
        logger.warning("Storage init failed: %s", e)
    await seed()

@app.on_event("shutdown")
async def on_stop():
    client.close()

# ---------- Seed ----------
async def ensure_seed_state():
    """Keep seeded demo accounts active and demo shops approved on every startup.
    Scoped strictly to known seed emails/shops so it never touches real user data."""
    await db.users.update_many(
        {"email": {"$in": ["admin@elaya.ph", "customer@elaya.ph", "owner@elaya.ph", "owner2@elaya.ph", "pending@elaya.ph"]}},
        {"$set": {"status": "active"}},
    )
    await db.shops.update_many({"shop_name": {"$in": ["Bloom & Petal", "Rosa Del Sol"]}}, {"$set": {"status": "approved"}})

async def seed():
    # Idempotent guard: keep the demo/seed accounts usable across restarts and test drift.
    await ensure_seed_state()
    if await db.users.count_documents({}) > 0:
        return
    admin = {"id": str(uuid.uuid4()), "name": "Admin", "email": "admin@elaya.ph", "password_hash": hash_pw("Admin123!"), "role": "admin", "status": "active", "created_at": now_iso()}
    customer = {"id": str(uuid.uuid4()), "name": "Maria Santos", "email": "customer@elaya.ph", "password_hash": hash_pw("Customer123!"), "role": "customer", "status": "active", "created_at": now_iso()}
    owner = {"id": str(uuid.uuid4()), "name": "Ana Reyes", "email": "owner@elaya.ph", "password_hash": hash_pw("Owner123!"), "role": "flower_owner", "status": "active", "created_at": now_iso()}
    owner2 = {"id": str(uuid.uuid4()), "name": "Bea Cruz", "email": "owner2@elaya.ph", "password_hash": hash_pw("Owner123!"), "role": "flower_owner", "status": "active", "created_at": now_iso()}
    pending_owner = {"id": str(uuid.uuid4()), "name": "Carlo Dela Peña", "email": "pending@elaya.ph", "password_hash": hash_pw("Owner123!"), "role": "flower_owner", "status": "active", "created_at": now_iso()}
    await db.users.insert_many([admin, customer, owner, owner2, pending_owner])

    permit = "https://images.unsplash.com/photo-1450101499163-c8848c66ca85?w=800"
    shop1 = {"id": str(uuid.uuid4()), "owner_id": owner["id"], "shop_name": "Bloom & Petal",
             "description": "Handcrafted bouquets in the heart of Biñan.", "location": "San Antonio, Biñan, Laguna",
             "lat": 14.3402, "lng": 121.0792, "image": "https://images.unsplash.com/photo-1771856558087-80f35365c3bb?w=800",
             "business_permit_url": permit, "owner_full_name": "Ana Reyes", "contact_number": "0917-100-2001",
             "owner_address": "Poblacion, Biñan, Laguna", "delivery_methods": DELIVERY_METHODS[:],
             "status": "approved", "reject_reason": None, "created_at": now_iso(), "reviewed_at": now_iso()}
    shop2 = {"id": str(uuid.uuid4()), "owner_id": owner2["id"], "shop_name": "Rosa Del Sol",
             "description": "Sun-kissed roses & lilies, delivered fresh.", "location": "Sto. Tomas, Biñan, Laguna",
             "lat": 14.3521, "lng": 121.0885, "image": "https://images.pexels.com/photos/6720583/pexels-photo-6720583.jpeg?w=800",
             "business_permit_url": permit, "owner_full_name": "Bea Cruz", "contact_number": "0917-100-2002",
             "owner_address": "Malaban, Biñan, Laguna", "delivery_methods": ["in_house", "pickup"],
             "status": "approved", "reject_reason": None, "created_at": now_iso(), "reviewed_at": now_iso()}
    shop3 = {"id": str(uuid.uuid4()), "owner_id": pending_owner["id"], "shop_name": "Petal Grove",
             "description": "Boutique floral studio (awaiting approval).", "location": "Canlalay, Biñan, Laguna",
             "lat": 14.3360, "lng": 121.0750, "image": "https://images.unsplash.com/photo-1490750967868-88aa4486c946?w=800",
             "business_permit_url": permit, "owner_full_name": "Carlo Dela Peña", "contact_number": "0917-100-2003",
             "owner_address": "Canlalay, Biñan, Laguna", "delivery_methods": DELIVERY_METHODS[:],
             "status": "pending", "reject_reason": None, "created_at": now_iso()}
    await db.shops.insert_many([shop1, shop2, shop3])

    A = "https://images.unsplash.com/photo-1561848355-890d054dc55a?w=800"
    B = "https://images.unsplash.com/photo-1519378058457-4c29a0a2efac?w=800"
    C = "https://images.unsplash.com/photo-1487070183336-b863922373d4?w=800"
    D = "https://images.unsplash.com/photo-1526047932273-341f2a7631f9?w=800"
    bouquets = [
        {"name": "Romantic Red Roses", "flowers_included": ["Red Rose"], "number_of_flowers": 12, "wrapping": "White Wrapper", "ribbon": "Red", "price": 850, "stock": 15,
         "images": [A, B, C, D], "description": "Classic dozen red roses, wrapped with love in Biñan.", "colors": ["#B91C1C"]},
        {"name": "Pink Blush Bouquet", "flowers_included": ["Pink Tulip", "Baby's Breath"], "number_of_flowers": 15, "wrapping": "Kraft Paper", "ribbon": "Pink", "price": 950, "stock": 10,
         "images": ["https://images.unsplash.com/photo-1523693916903-027d144a2b7d?w=800", "https://images.unsplash.com/photo-1509719662282-e8d17d92b31d?w=800", "https://images.unsplash.com/photo-1494972308805-463bc619d34e?w=800"], "description": "Soft pastel arrangement for gentle moments.", "colors": ["#FF7EB3"]},
        {"name": "Sunny Delight", "flowers_included": ["Sunflower"], "number_of_flowers": 8, "wrapping": "Cream Wrapper", "ribbon": "Yellow", "price": 780, "stock": 12,
         "images": ["https://images.pexels.com/photos/20278829/pexels-photo-20278829.jpeg?w=800", "https://images.unsplash.com/photo-1470509037663-253afd7f0f51?w=800", "https://images.unsplash.com/photo-1597848212624-a19eb35e2651?w=800"], "description": "Bright sunflowers to brighten any day.", "colors": ["#FBBF24"]},
        {"name": "White Lily Grace", "flowers_included": ["White Lily"], "number_of_flowers": 10, "wrapping": "Transparent Wrap", "ribbon": "Ivory", "price": 1050, "stock": 8,
         "images": ["https://images.unsplash.com/photo-1587304975230-2ce70e2f8a25?w=800", "https://images.unsplash.com/photo-1520763185298-1b434c919102?w=800", "https://images.unsplash.com/photo-1508610048659-a06b669e3321?w=800"], "description": "Elegant lilies symbolising purity.", "colors": ["#FFFFFF"]},
    ]
    shops = [shop1, shop2]
    for i, b in enumerate(bouquets):
        s = shops[i % 2]
        imgs = b["images"]
        await db.products.insert_one({"id": str(uuid.uuid4()), "shop_id": s["id"], "owner_id": s["owner_id"], "product_type": "bouquet",
                                      "availability": True, "status": "active", "created_at": now_iso(), "image": imgs[0], **b})
    logger.info("Seeded demo data")
