"""Admin panel API: service keys, accounts, offers and match reports.

Access is one password, ADMIN_PASSWORD in /etc/destinyos.env (deploy.sh creates it; it cannot be set from the panel).
Signing in gives a 12-hour cookie limited to /api/admin. Every change is written to the events table.
"""
from __future__ import annotations
import hmac, os, re, secrets, time
from collections import defaultdict, deque
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

import auth, billing, conf, db, reports

router = APIRouter(prefix="/api/admin")
COOKIE, HOURS = "dos_admin", 12
_tries: dict[str, deque] = defaultdict(deque)
CREATED_TEXT = "Account created by the Destiny OS team at this person's request, with the details they provided."


def _password() -> str:
    return os.getenv("ADMIN_PASSWORD", "")


def admin_only(req: Request):
    tok = req.cookies.get(COOKIE)
    if not tok or not db.one("SELECT 1 FROM admin_sessions WHERE token_hash=? AND expires_at>?", auth._h("admin|" + tok), db.now()):
        raise HTTPException(401, "Sign in to the admin panel.")


class LoginIn(BaseModel):
    password: str = Field(max_length=200)


@router.post("/login")
def login(body: LoginIn, req: Request, resp: Response):
    if len(_password()) < 12:
        raise HTTPException(503, "The admin panel is not set up on this server yet. Run the deploy script once.")
    ip = req.client.host if req.client else "?"
    q, now = _tries[ip], time.time()
    while q and q[0] < now - 900:
        q.popleft()
    if len(q) >= 5:
        raise HTTPException(429, "Too many attempts. Try again in 15 minutes.")
    if not hmac.compare_digest(body.password.encode(), _password().encode()):
        q.append(now)
        db.log_event(None, "admin_login_failed", {"ip": ip})
        raise HTTPException(401, "That password isn't right.")
    tok = secrets.token_urlsafe(32)
    with db.tx() as c:
        c.execute("DELETE FROM admin_sessions WHERE expires_at<?", (db.now(),))
        c.execute("INSERT INTO admin_sessions(token_hash, expires_at) VALUES (?,?)", (auth._h("admin|" + tok), db.now() + HOURS * 3600))
    resp.set_cookie(COOKIE, tok, max_age=HOURS * 3600, httponly=True, secure=auth.COOKIE_SECURE, samesite="strict", path="/api/admin")
    db.log_event(None, "admin_login", {"ip": ip})
    return {"ok": True}


@router.post("/logout")
def logout(req: Request, resp: Response):
    tok = req.cookies.get(COOKIE)
    if tok:
        with db.tx() as c:
            c.execute("DELETE FROM admin_sessions WHERE token_hash=?", (auth._h("admin|" + tok),))
    resp.delete_cookie(COOKIE, path="/api/admin")
    return {"ok": True}


# ── Overview ──
@router.get("/overview", dependencies=[Depends(admin_only)])
def overview():
    n = lambda sql, *a: db.one(sql, *a)["n"]
    week = db.now() - 7 * 86400
    eff = conf.effective()
    return {
        "users": n("SELECT COUNT(*) n FROM users"), "users_week": n("SELECT COUNT(*) n FROM users WHERE created_at>?", week),
        "reports": n("SELECT COUNT(*) n FROM reports WHERE kind='core'"),
        "three_year": n("SELECT COUNT(*) n FROM purchases WHERE item='three_year' AND status IN ('paid','fulfilled')"),
        "sessions": n("SELECT COUNT(*) n FROM purchases WHERE item='consultation' AND status IN ('paid','fulfilled')"),
        "revenue_inr": n("SELECT COALESCE(SUM(amount_paise),0) n FROM purchases WHERE status IN ('paid','fulfilled')") // 100,
        "subscribers": n("SELECT COUNT(DISTINCT user_id) n FROM subscriptions WHERE status='active'"),
        "halia_on": n("SELECT COUNT(*) n FROM halia_settings"), "match_profiles": n("SELECT COUNT(*) n FROM match_profiles"),
        "matches": n("SELECT COUNT(*) n FROM matches"),
        "ready": {"ai": bool(eff["ANTHROPIC_API_KEY"] or eff["KIMI_API_KEY"]), "sms": bool(eff["MSG91_AUTH_KEY"] and eff["MSG91_TEMPLATE_ID"]),
                  "payments": bool(eff["RAZORPAY_KEY_ID"] and eff["RAZORPAY_KEY_SECRET"]),
                  "whatsapp": bool(eff["WA_TOKEN"] and eff["WA_PHONE_ID"])},
    }


# ── Service keys ──
@router.get("/settings", dependencies=[Depends(admin_only)])
def settings_get():
    return {"settings": conf.status()}


class SettingsIn(BaseModel):
    values: dict[str, str]


@router.put("/settings", dependencies=[Depends(admin_only)])
def settings_put(body: SettingsIn):
    try:
        conf.save(body.values)
    except ValueError as e:
        raise HTTPException(422, str(e))
    db.log_event(None, "admin_settings", {"keys": sorted(body.values)})        # names only, never values
    return {"ok": True, "settings": conf.status()}


@router.post("/settings/test-ai", dependencies=[Depends(admin_only)])
def test_ai():
    """One tiny request to the model, to prove the key works."""
    import main
    try:
        out = main.ask_claude("Reply with the single word: ready", [{"role": "user", "content": "Are you there?"}],
                              model=main.FAST_MODEL, max_tokens=20)
    except HTTPException:
        return {"ok": False, "detail": "The model did not answer. Check the key and that the account has credit."}
    return {"ok": True, "detail": out[:60]}


# ── Accounts ──
def _row(u: dict) -> dict:
    return {"id": u["id"], "name": u["name"], "phone": u["phone"], "city": u["city"], "dob": u["dob"], "created_at": u["created_at"],
            "source": u["source"], "tier": billing.tier(u["id"]),
            "has_report": bool(db.one("SELECT 1 FROM reports WHERE user_id=? AND kind='core'", u["id"])),
            "three_year": billing.has_item(u["id"], "three_year")}


@router.get("/users", dependencies=[Depends(admin_only)])
def users(q: str = "", offset: int = 0):
    q = q.strip()[:60]
    like = f"%{q}%"
    rows = db.all_("SELECT * FROM users WHERE name LIKE ? OR phone LIKE ? OR city LIKE ? ORDER BY created_at DESC, id DESC LIMIT 50 OFFSET ?",
                   like, like, like, max(0, offset))
    total = db.one("SELECT COUNT(*) n FROM users WHERE name LIKE ? OR phone LIKE ? OR city LIKE ?", like, like, like)["n"]
    return {"users": [_row(u) for u in rows], "total": total}


def _user(uid: int) -> dict:
    u = db.one("SELECT * FROM users WHERE id=?", uid)
    if not u:
        raise HTTPException(404, "No such account.")
    return u


@router.get("/users/{uid}", dependencies=[Depends(admin_only)])
def user_get(uid: int):
    u = _user(uid)
    return {**_row(u), "birth_time": u["birth_time"], "language": u.get("language") or "en", "whatsapp_optin": bool(u["whatsapp_optin"]),
            "plan": {k: v for k, v in billing.plan_status(uid).items() if k in ("tier", "status", "paid_until", "renews")},
            "purchases": db.all_("SELECT id, item, amount_paise, status, coupon, provider_order_id, created_at FROM purchases "
                                 "WHERE user_id=? AND status!='created' ORDER BY id DESC", uid),
            "grants": db.all_("SELECT id, plan, current_end FROM subscriptions WHERE user_id=? AND provider_sub_id LIKE 'grant_%' "
                              "AND current_end>? ORDER BY id DESC", uid, db.now()),
            "halia_answers": db.one("SELECT COUNT(DISTINCT field) n FROM halia_answers WHERE user_id=?", uid)["n"],
            "match_profile": bool(db.one("SELECT 1 FROM match_profiles WHERE user_id=?", uid))}


class UserIn(BaseModel):
    phone: str = Field(max_length=20)
    name: str = Field(min_length=2, max_length=120)
    dob: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    birth_time: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    city: str = Field(min_length=2, max_length=120)
    language: str = Field(default="en", pattern=r"^(en|hi)$")
    whatsapp_optin: bool = False


@router.post("/users", dependencies=[Depends(admin_only)])
def user_create(body: UserIn):
    phone = auth.normalise_phone(body.phone)
    try:
        born = date.fromisoformat(body.dob)
    except ValueError:
        raise HTTPException(422, "That date of birth doesn't exist.")
    if born > date.today() or born.year < 1900:
        raise HTTPException(422, "Check the date of birth.")
    if db.one("SELECT 1 FROM users WHERE phone=?", phone):
        raise HTTPException(409, "That number already has an account.")
    with db.tx() as c:
        cur = c.execute("INSERT INTO users(phone, name, dob, birth_time, city, source, consent_at, consent_text, whatsapp_optin, "
                        "free_questions_used, created_at, language) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                        (phone, body.name.strip(), body.dob, body.birth_time, body.city.strip(), "admin", db.now(), CREATED_TEXT,
                         int(body.whatsapp_optin), reports.questions_used_before(phone), db.now(), body.language))
    db.log_event(cur.lastrowid, "admin_user_created")
    return {"ok": True, "id": cur.lastrowid}


@router.delete("/users/{uid}", dependencies=[Depends(admin_only)])
def user_delete(uid: int):
    import main
    main.erase_user(_user(uid))
    db.log_event(None, "admin_user_deleted", {"id": uid})
    return {"ok": True}


# ── Offers: a free item, free days on a plan, or a discount code ──
class GrantIn(BaseModel):
    item: str | None = None
    plan: str | None = None
    days: int = Field(default=30, ge=1, le=366)


@router.post("/users/{uid}/grant", dependencies=[Depends(admin_only)])
def grant(uid: int, body: GrantIn):
    _user(uid)
    ref = f"grant_{uid}_{db.now()}_{secrets.token_hex(3)}"
    if body.item:
        if body.item not in billing.ADDONS:
            raise HTTPException(404, "Unknown item.")
        with db.tx() as c:
            c.execute("INSERT INTO purchases(user_id, item, amount_paise, provider_order_id, status, details, created_at) "
                      "VALUES (?,?,0,?,'paid','{}',?)", (uid, body.item, ref, db.now()))
    elif body.plan:
        if body.plan not in billing.PLANS:
            raise HTTPException(404, "Unknown plan.")
        with db.tx() as c:       # 'cancelled' with a future end date = access until then, and nothing renews
            c.execute("INSERT INTO subscriptions(user_id, provider_sub_id, status, current_end, updated_at, plan) VALUES (?,?,'cancelled',?,?,?)",
                      (uid, ref, db.now() + body.days * 86400, db.now(), body.plan))
    else:
        raise HTTPException(422, "Choose an item or a plan.")
    db.log_event(uid, "admin_grant", {"item": body.item, "plan": body.plan, "days": body.days if body.plan else None})
    return {"ok": True}


@router.delete("/users/{uid}/grant/{sub_id}", dependencies=[Depends(admin_only)])
def grant_end(uid: int, sub_id: int):
    with db.tx() as c:
        c.execute("UPDATE subscriptions SET current_end=?, updated_at=? WHERE id=? AND user_id=? AND provider_sub_id LIKE 'grant_%'",
                  (db.now() - 1, db.now(), sub_id, uid))
    db.log_event(uid, "admin_grant_ended", {"sub": sub_id})
    return {"ok": True}


class CouponIn(BaseModel):
    code: str = Field(min_length=3, max_length=24)
    percent: int = Field(ge=1, le=100)
    item: str | None = None
    max_uses: int = Field(default=1, ge=1, le=100000)
    days: int | None = Field(default=None, ge=1, le=366)
    note: str = Field(default="", max_length=120)


@router.get("/coupons", dependencies=[Depends(admin_only)])
def coupons():
    rows = db.all_("SELECT * FROM coupons ORDER BY created_at DESC")
    for r in rows:
        r["used"] = billing.coupon_uses(r["code"])
    return {"coupons": rows, "items": {k: v["name"] for k, v in billing.ADDONS.items()}, "plans": {k: v["name"] for k, v in billing.PLANS.items()}}


@router.post("/coupons", dependencies=[Depends(admin_only)])
def coupon_create(body: CouponIn):
    code = re.sub(r"[^A-Z0-9]", "", body.code.upper())
    if len(code) < 3:
        raise HTTPException(422, "Use at least 3 letters or numbers.")
    if body.item and body.item not in billing.ADDONS:
        raise HTTPException(404, "Unknown item.")
    if db.one("SELECT 1 FROM coupons WHERE code=?", code):
        raise HTTPException(409, "That code already exists.")
    with db.tx() as c:
        c.execute("INSERT INTO coupons(code, percent, item, max_uses, expires_at, active, note, created_at) VALUES (?,?,?,?,?,1,?,?)",
                  (code, body.percent, body.item or None, body.max_uses, db.now() + body.days * 86400 if body.days else None,
                   body.note.strip(), db.now()))
    db.log_event(None, "admin_coupon", {"code": code, "percent": body.percent})
    return {"ok": True, "code": code}


@router.delete("/coupons/{code}", dependencies=[Depends(admin_only)])
def coupon_off(code: str):
    with db.tx() as c:
        c.execute("UPDATE coupons SET active=0 WHERE code=?", (code.upper(),))
    return {"ok": True}


# ── Match reports ──
@router.get("/match-reports", dependencies=[Depends(admin_only)])
def match_reports():
    return {"reports": db.all_(
        "SELECT b.id, b.reason, b.at, b.target_id, t.name target_name, t.phone target_phone, b.user_id, r.name reporter_name, "
        "(SELECT COUNT(*) FROM match_blocks x WHERE x.target_id=b.target_id) times, "
        "(SELECT active FROM match_profiles p WHERE p.user_id=b.target_id) active "
        "FROM match_blocks b JOIN users t ON t.id=b.target_id JOIN users r ON r.id=b.user_id ORDER BY b.at DESC LIMIT 100")}


@router.post("/match-profiles/{uid}/hide", dependencies=[Depends(admin_only)])
def match_hide(uid: int):
    with db.tx() as c:
        c.execute("UPDATE match_profiles SET active=0 WHERE user_id=?", (uid,))
    db.log_event(uid, "admin_match_hidden")
    return {"ok": True}
