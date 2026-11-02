"""Razorpay: ₹599/month Destiny Plus subscription (UPI AutoPay / card mandate) and one-time add-ons.

Setup (Razorpay dashboard):
  - Subscriptions → Plans → create "Destiny Plus", monthly, ₹599 → copy plan_… id into RAZORPAY_PLAN_ID
  - Settings → API keys → RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET
  - Settings → Webhooks → URL https://destinyos.in/api/billing/webhook, secret → RAZORPAY_WEBHOOK_SECRET
    events: subscription.activated, subscription.charged, subscription.pending, subscription.halted,
            subscription.cancelled, subscription.completed, order.paid
"""
from __future__ import annotations
import hashlib, hmac, json, logging, os

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

import db
from auth import current_user

log = logging.getLogger("destinyos.billing")
router = APIRouter(prefix="/api/billing")

KEY_ID = os.getenv("RAZORPAY_KEY_ID", "")
KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET", "")
PLAN_ID = os.getenv("RAZORPAY_PLAN_ID", "")
WEBHOOK_SECRET = os.getenv("RAZORPAY_WEBHOOK_SECRET", "")
API = "https://api.razorpay.com/v1"

PLAN = {"name": "Destiny Plus", "price_inr": 599, "period": "month"}
ADDONS = {   # amounts in paise
    "consultation":  {"name": "One-to-one consultation with Dr. Krish (45 min)", "amount": 299900},
    "compatibility": {"name": "Compatibility report", "amount": 99900},
    "annual":        {"name": "Annual forecast", "amount": 199900},
}
GRACE_SECONDS = 3 * 86400   # keep access for 3 days while a renewal payment is retried


def configured() -> bool:
    return bool(KEY_ID and KEY_SECRET and PLAN_ID)


def _rzp(method: str, path: str, **kw) -> dict:
    if not (KEY_ID and KEY_SECRET):
        raise HTTPException(503, "Payments aren't switched on yet. Please try again soon.")
    r = httpx.request(method, API + path, auth=(KEY_ID, KEY_SECRET), timeout=20, **kw)
    if r.status_code >= 400:
        log.error("Razorpay %s %s -> %s %s", method, path, r.status_code, r.text[:400])
        raise HTTPException(502, "The payment service didn't respond. Please try again.")
    return r.json()


def _sig_ok(message: str, signature: str, secret: str) -> bool:
    exp = hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()
    return bool(signature) and hmac.compare_digest(exp, signature)


# ── Access ──
def subscription(user_id: int) -> dict | None:
    """The subscription to show and manage: a qualifying one first, then the most recent."""
    rows = db.all_("SELECT * FROM subscriptions WHERE user_id=? ORDER BY updated_at DESC, id DESC", user_id)
    live = [r for r in rows if _row_grants(r)]
    return (live or rows or [None])[0]


def _row_grants(s: dict) -> bool:
    if s["status"] == "active":
        return True
    end = s["current_end"] or 0
    if s["status"] in ("cancelled", "completed") and end > db.now():
        return True                                   # cancelled but paid until period end
    if s["status"] in ("pending", "halted") and end + GRACE_SECONDS > db.now():
        return True                                   # renewal being retried
    return False


def is_subscriber(user_id: int) -> bool:
    """Access if ANY of the user's subscriptions qualifies (a late webhook on an old one mustn't hide a live one)."""
    return any(_row_grants(s) for s in db.all_("SELECT * FROM subscriptions WHERE user_id=?", user_id))


def plan_status(user_id: int) -> dict:
    s = subscription(user_id)
    return {"subscribed": is_subscriber(user_id),
            "status": s["status"] if s else None,
            "paid_until": s["current_end"] if s else None,
            "plan": PLAN, "payments_ready": configured()}


def require_subscriber(user=Depends(current_user)) -> dict:
    if not is_subscriber(user["id"]):
        raise HTTPException(402, "This is part of Destiny Plus. Subscribe for ₹599/month to unlock it.")
    return user


def _upsert_sub(user_id: int, sub_id: str, status: str, current_end: int | None):
    with db.tx() as c:
        c.execute("INSERT INTO subscriptions(user_id, provider_sub_id, status, current_end, updated_at) "
                  "VALUES (?,?,?,?,?) ON CONFLICT(provider_sub_id) DO UPDATE SET status=excluded.status, "
                  "current_end=COALESCE(excluded.current_end, subscriptions.current_end), updated_at=excluded.updated_at",
                  (user_id, sub_id, status, current_end, db.now()))


# ── Subscription ──
@router.get("/status")
def status(user=Depends(current_user)):
    return plan_status(user["id"])


@router.post("/subscribe")
def subscribe(user=Depends(current_user)):
    if is_subscriber(user["id"]):
        raise HTTPException(409, "You're already on Destiny Plus.")
    if not configured():
        raise HTTPException(503, "Payments aren't switched on yet. Please try again soon.")
    s = _rzp("POST", "/subscriptions", json={
        "plan_id": PLAN_ID, "total_count": 120, "customer_notify": 1, "quantity": 1,
        "notes": {"user_id": str(user["id"])}})
    _upsert_sub(user["id"], s["id"], s.get("status", "created"), None)
    db.log_event(user["id"], "subscribe_start", {"sub": s["id"]})
    return {"key_id": KEY_ID, "subscription_id": s["id"], "name": user["name"], "phone": user["phone"],
            "description": f"{PLAN['name']} · ₹{PLAN['price_inr']}/month"}


class SubVerifyIn(BaseModel):
    razorpay_payment_id: str = Field(max_length=60)
    razorpay_subscription_id: str = Field(max_length=60)
    razorpay_signature: str = Field(max_length=200)


@router.post("/subscribe/verify")
def subscribe_verify(body: SubVerifyIn, user=Depends(current_user)):
    """Called by Razorpay Checkout's success handler. The webhook is the source of truth; this
    just unlocks access immediately so the customer doesn't wait for it."""
    own = db.one("SELECT * FROM subscriptions WHERE provider_sub_id=? AND user_id=?",
                 body.razorpay_subscription_id, user["id"])
    if not own or not _sig_ok(f"{body.razorpay_payment_id}|{body.razorpay_subscription_id}",
                              body.razorpay_signature, KEY_SECRET):
        raise HTTPException(400, "We couldn't verify that payment. If money was taken, it will be confirmed shortly.")
    s = _rzp("GET", f"/subscriptions/{body.razorpay_subscription_id}")
    _upsert_sub(user["id"], s["id"], s.get("status", "active"), s.get("current_end"))
    db.log_event(user["id"], "subscribe_paid", {"sub": s["id"], "status": s.get("status")})
    return plan_status(user["id"])


@router.post("/cancel")
def cancel(user=Depends(current_user)):
    s = subscription(user["id"])
    if not s or s["status"] in ("cancelled", "completed"):
        raise HTTPException(409, "There's no active subscription to cancel.")
    r = _rzp("POST", f"/subscriptions/{s['provider_sub_id']}/cancel", json={"cancel_at_cycle_end": 1})
    # Razorpay keeps it 'active' until cycle end; mark our intent so the panel can say so
    db.log_event(user["id"], "subscribe_cancel", {"sub": s["provider_sub_id"]})
    _upsert_sub(user["id"], s["provider_sub_id"], r.get("status", s["status"]), r.get("current_end"))
    return {**plan_status(user["id"]), "cancel_at_period_end": True}


# ── Add-ons (one-time orders) ──
class OrderIn(BaseModel):
    item: str
    details: dict | None = None    # compatibility: partner name/dob/time/city


@router.post("/order")
def order(body: OrderIn, user=Depends(current_user)):
    a = ADDONS.get(body.item)
    if not a:
        raise HTTPException(404, "Unknown item.")
    if body.item == "compatibility":
        d = body.details or {}
        if not (d.get("name") and d.get("dob")):
            raise HTTPException(422, "Add your partner's name and date of birth.")
    o = _rzp("POST", "/orders", json={"amount": a["amount"], "currency": "INR",
                                       "receipt": f"u{user['id']}-{body.item}-{db.now()}",
                                       "notes": {"user_id": str(user["id"]), "item": body.item}})
    with db.tx() as c:
        c.execute("INSERT INTO purchases(user_id, item, amount_paise, provider_order_id, status, details, created_at) "
                  "VALUES (?,?,?,?,?,?,?)", (user["id"], body.item, a["amount"], o["id"], "created",
                                              json.dumps(body.details or {})[:2000], db.now()))
    return {"key_id": KEY_ID, "order_id": o["id"], "amount": a["amount"], "description": a["name"],
            "name": user["name"], "phone": user["phone"]}


class OrderVerifyIn(BaseModel):
    razorpay_payment_id: str = Field(max_length=60)
    razorpay_order_id: str = Field(max_length=60)
    razorpay_signature: str = Field(max_length=200)


def mark_paid(order_id: str, payment_id: str | None) -> dict | None:
    with db.tx() as c:
        c.execute("UPDATE purchases SET status='paid', provider_payment_id=COALESCE(?, provider_payment_id) "
                  "WHERE provider_order_id=? AND status='created'", (payment_id, order_id))
    return db.one("SELECT * FROM purchases WHERE provider_order_id=?", order_id)


@router.post("/order/verify")
def order_verify(body: OrderVerifyIn, user=Depends(current_user)):
    p = db.one("SELECT * FROM purchases WHERE provider_order_id=? AND user_id=?", body.razorpay_order_id, user["id"])
    if not p or not _sig_ok(f"{body.razorpay_order_id}|{body.razorpay_payment_id}", body.razorpay_signature, KEY_SECRET):
        raise HTTPException(400, "We couldn't verify that payment. If money was taken, it will be confirmed shortly.")
    p = mark_paid(body.razorpay_order_id, body.razorpay_payment_id)
    db.log_event(user["id"], "addon_paid", {"item": p["item"]})
    return {"ok": True, "item": p["item"], "purchase_id": p["id"]}


@router.get("/purchases")
def purchases(user=Depends(current_user)):
    rows = db.all_("SELECT id, item, status, created_at FROM purchases WHERE user_id=? AND status!='created' "
                   "ORDER BY created_at DESC", user["id"])
    return {"purchases": rows, "addons": {k: {"name": v["name"], "price_inr": v["amount"] // 100} for k, v in ADDONS.items()}}


# ── Webhook (source of truth) ──
@router.post("/webhook")
async def webhook(req: Request):
    raw = await req.body()
    if not WEBHOOK_SECRET or not _sig_ok(raw.decode("utf-8", "replace"), req.headers.get("x-razorpay-signature", ""), WEBHOOK_SECRET):
        raise HTTPException(400, "Bad signature.")
    ev = json.loads(raw)
    kind = ev.get("event", "")
    payload = ev.get("payload", {})
    if kind.startswith("subscription."):
        s = payload.get("subscription", {}).get("entity", {})
        # Only subscriptions we created for a live account; never trust notes.user_id (ids of deleted users).
        row = db.one("SELECT user_id FROM subscriptions WHERE provider_sub_id=?", s.get("id", ""))
        if row:
            _upsert_sub(row["user_id"], s["id"], s.get("status", kind.split(".")[1]), s.get("current_end"))
            db.log_event(row["user_id"], "webhook_" + kind, {"status": s.get("status")})
    elif kind == "order.paid":
        o = payload.get("order", {}).get("entity", {})
        pay = payload.get("payment", {}).get("entity", {})
        mark_paid(o.get("id", ""), pay.get("id"))
    return {"ok": True}
