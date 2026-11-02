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
PLAN_ID = os.getenv("RAZORPAY_PLAN_ID", "")                # ₹599/month Destiny Plus
PLAN_ID_VOICE = os.getenv("RAZORPAY_PLAN_ID_VOICE", "")    # ₹999/month Destiny Voice
WEBHOOK_SECRET = os.getenv("RAZORPAY_WEBHOOK_SECRET", "")
API = "https://api.razorpay.com/v1"

PLANS = {
    "plus":  {"name": "Destiny Plus", "price_inr": 599, "period": "month"},
    "voice": {"name": "Destiny Voice", "price_inr": 999, "period": "month", "voice_minutes": 60},
}
PLAN = PLANS["plus"]


def plan_id(plan: str) -> str:
    return {"plus": PLAN_ID, "voice": PLAN_ID_VOICE}.get(plan, "")
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


def is_voice(user_id: int) -> bool:
    return any(_row_grants(s) for s in db.all_("SELECT * FROM subscriptions WHERE user_id=? AND plan='voice'", user_id))


def tier(user_id: int) -> str:
    return "voice" if is_voice(user_id) else "plus" if is_subscriber(user_id) else "free"


def plan_status(user_id: int) -> dict:
    s = subscription(user_id)
    if is_voice(user_id):
        s = next((r for r in db.all_("SELECT * FROM subscriptions WHERE user_id=? AND plan='voice' "
                                     "ORDER BY updated_at DESC", user_id) if _row_grants(r)), s)
    t = tier(user_id)
    return {"subscribed": t != "free", "tier": t,
            "status": s["status"] if s else None,
            "paid_until": s["current_end"] if s else None,
            "renews": bool(s and s["status"] == "active" and not s.get("cancel_requested")),
            "plan": PLANS.get(t, PLAN), "plans": PLANS,
            "payments_ready": configured(), "voice_ready": bool(PLAN_ID_VOICE and configured())}


def require_subscriber(user=Depends(current_user)) -> dict:
    if not is_subscriber(user["id"]):
        raise HTTPException(402, "This is part of Destiny Plus. Subscribe for ₹599/month to unlock it.")
    return user


def require_voice(user=Depends(current_user)) -> dict:
    if not is_voice(user["id"]):
        raise HTTPException(402, "Voice chat is part of Destiny Voice. Upgrade for ₹999/month to talk to Dr. Krish's AI voice guide.")
    return user


def _upsert_sub(user_id: int, sub_id: str, status: str, current_end: int | None, plan: str | None = None):
    with db.tx() as c:
        c.execute("INSERT INTO subscriptions(user_id, provider_sub_id, status, current_end, updated_at, plan) "
                  "VALUES (?,?,?,?,?,?) ON CONFLICT(provider_sub_id) DO UPDATE SET status=excluded.status, "
                  "current_end=COALESCE(excluded.current_end, subscriptions.current_end), updated_at=excluded.updated_at",
                  (user_id, sub_id, status, current_end, db.now(), plan or "plus"))


def _retire_plus(user_id: int):
    """After an upgrade to Voice is paid, stop the old ₹599 plan from renewing so the customer isn't billed
    twice. It ends at the close of the period already paid for (no money lost); Voice covers everything in
    Plus meanwhile. Safe to call repeatedly: /api/me retries it until Razorpay accepts."""
    for r in db.all_("SELECT * FROM subscriptions WHERE user_id=? AND plan='plus' AND cancel_requested=0 "
                     "AND status NOT IN ('cancelled','completed','expired')", user_id):
        try:
            _rzp("POST", f"/subscriptions/{r['provider_sub_id']}/cancel", json={"cancel_at_cycle_end": 1})
        except HTTPException:
            log.error("could not stop old Plus subscription %s on upgrade; will retry", r["provider_sub_id"])
            db.log_event(user_id, "plus_retire_failed", {"sub": r["provider_sub_id"]})
            continue
        with db.tx() as c:
            c.execute("UPDATE subscriptions SET cancel_requested=1, updated_at=? WHERE id=?", (db.now(), r["id"]))
        db.log_event(user_id, "plus_retired_on_upgrade", {"sub": r["provider_sub_id"]})


def retire_plus_if_needed(user_id: int):
    """Called on /api/me: finish an upgrade whose Plus cancellation didn't go through the first time."""
    if not configured() or not is_voice(user_id):
        return
    voice_live = db.one("SELECT 1 FROM subscriptions WHERE user_id=? AND plan='voice' AND status='active'", user_id)
    pending = db.one("SELECT 1 FROM subscriptions WHERE user_id=? AND plan='plus' AND cancel_requested=0 "
                     "AND status NOT IN ('cancelled','completed','expired')", user_id)
    if voice_live and pending:
        _retire_plus(user_id)


# ── Subscription ──
@router.get("/status")
def status(user=Depends(current_user)):
    return plan_status(user["id"])


class SubscribeIn(BaseModel):
    plan: str = "plus"


@router.post("/subscribe")
def subscribe(body: SubscribeIn | None = None, user=Depends(current_user)):
    plan = (body.plan if body else "plus")
    if plan not in PLANS:
        raise HTTPException(404, "Unknown plan.")
    t = tier(user["id"])
    if t == "voice" or (t == "plus" and plan == "plus"):
        raise HTTPException(409, f"You're already on {PLANS[t]['name']}.")
    if not configured() or not plan_id(plan):
        raise HTTPException(503, "Payments aren't switched on yet. Please try again soon.")
    s = _rzp("POST", "/subscriptions", json={
        "plan_id": plan_id(plan), "total_count": 120, "customer_notify": 1, "quantity": 1,
        "notes": {"user_id": str(user["id"]), "plan": plan}})
    _upsert_sub(user["id"], s["id"], s.get("status", "created"), None, plan)
    db.log_event(user["id"], "subscribe_start", {"sub": s["id"], "plan": plan})
    p = PLANS[plan]
    return {"key_id": KEY_ID, "subscription_id": s["id"], "name": user["name"], "phone": user["phone"],
            "description": f"{p['name']} · ₹{p['price_inr']}/month", "plan": plan}


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
    _upsert_sub(user["id"], s["id"], s.get("status", "active"), s.get("current_end"), own["plan"])
    db.log_event(user["id"], "subscribe_paid", {"sub": s["id"], "status": s.get("status"), "plan": own["plan"]})
    if own["plan"] == "voice" and is_voice(user["id"]):
        _retire_plus(user["id"])
    return plan_status(user["id"])


@router.post("/cancel")
def cancel(user=Depends(current_user)):
    # cancel the plan the customer is paying for now: Voice first, then Plus; skip ones already stopping
    rows = db.all_("SELECT * FROM subscriptions WHERE user_id=? AND cancel_requested=0 AND status NOT IN "
                   "('cancelled','completed','expired') ORDER BY (plan='voice') DESC, updated_at DESC, id DESC", user["id"])
    s = next((r for r in rows if _row_grants(r)), None)
    if not s:
        raise HTTPException(409, "There's no active subscription to cancel.")
    r = _rzp("POST", f"/subscriptions/{s['provider_sub_id']}/cancel", json={"cancel_at_cycle_end": 1})
    # Razorpay keeps it 'active' until cycle end; mark our intent so the panel can say so
    db.log_event(user["id"], "subscribe_cancel", {"sub": s["provider_sub_id"]})
    with db.tx() as c:
        c.execute("UPDATE subscriptions SET cancel_requested=1 WHERE id=?", (s["id"],))
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
            sub = db.one("SELECT plan FROM subscriptions WHERE provider_sub_id=?", s["id"])
            if sub and sub["plan"] == "voice" and kind in ("subscription.activated", "subscription.charged") and is_voice(row["user_id"]):
                _retire_plus(row["user_id"])
    elif kind == "order.paid":
        o = payload.get("order", {}).get("entity", {})
        pay = payload.get("payment", {}).get("entity", {})
        mark_paid(o.get("id", ""), pay.get("id"))
    return {"ok": True}
