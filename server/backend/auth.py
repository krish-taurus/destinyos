"""Phone-OTP accounts and cookie sessions.

Flow:
  1. POST /api/auth/otp          {phone}                    -> OTP sent (SMS via MSG91)
  2. POST /api/auth/verify       {phone, code}              -> existing user: session cookie set
                                                              new user: {needs_registration, signup_token}
  3. POST /api/auth/register     {signup_token, birth details, consent} -> user created, session cookie set
"""
from __future__ import annotations
import hashlib, hmac, logging, os, re, secrets, time
from datetime import date

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

import db
import reports

log = logging.getLogger("destinyos.auth")
router = APIRouter(prefix="/api/auth")

SECRET = os.getenv("SESSION_SECRET") or secrets.token_hex(32)   # set in /etc/destinyos.env so sessions survive restarts
COOKIE = "dos_session"
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "1") == "1"
SESSION_DAYS = 60
OTP_TTL = 600            # 10 minutes
OTP_RESEND_GAP = 30      # seconds between sends
OTP_MAX_PER_DAY = 5
OTP_MAX_ATTEMPTS = 5

MSG91_AUTH_KEY = os.getenv("MSG91_AUTH_KEY", "")
MSG91_TEMPLATE_ID = os.getenv("MSG91_TEMPLATE_ID", "")
# Dev mode: no SMS is sent; the code is written to the server log (journalctl -u destinyos-api).
OTP_DEV_MODE = os.getenv("OTP_DEV_MODE", "0" if MSG91_AUTH_KEY else "1") == "1"

CONSENT_TEXT = ("I consent to Destiny OS storing my name, phone number and birth details to generate and "
                "save my reports and guidance. I understand astrology and numerology guidance is traditional "
                "and reflective, not predictive, and doesn't replace medical, legal, financial or "
                "mental-health advice. I can delete my account and data at any time.")


def _h(s: str) -> str:
    return hmac.new(SECRET.encode(), s.encode(), hashlib.sha256).hexdigest()


def normalise_phone(raw: str) -> str:
    p = re.sub(r"[^\d+]", "", raw or "")
    if p.startswith("00"):
        p = "+" + p[2:]
    if re.fullmatch(r"[6-9]\d{9}", p):                 # Indian mobile without country code
        p = "+91" + p
    elif re.fullmatch(r"91[6-9]\d{9}", p):
        p = "+" + p
    if not re.fullmatch(r"\+[1-9]\d{7,14}", p):
        raise HTTPException(422, "Enter a valid mobile number.")
    return p


def send_sms_otp(phone: str, code: str):
    if OTP_DEV_MODE:
        log.warning("OTP for %s: %s (dev mode, no SMS sent)", phone[:-4] + "****", code)
        return
    r = httpx.post("https://control.msg91.com/api/v5/otp",
                   params={"template_id": MSG91_TEMPLATE_ID, "mobile": phone.lstrip("+"), "otp": code},
                   headers={"authkey": MSG91_AUTH_KEY, "accept": "application/json"}, timeout=15)
    if r.status_code >= 400 or (r.headers.get("content-type", "").startswith("application/json")
                                and r.json().get("type") == "error"):
        log.error("MSG91 error %s: %s", r.status_code, r.text[:300])
        raise HTTPException(502, "Couldn't send the code right now. Try again in a minute.")


# ── Sessions ──
def create_session(resp: Response, user_id: int):
    token = secrets.token_urlsafe(32)
    with db.tx() as c:
        c.execute("INSERT INTO sessions(token_hash, user_id, expires_at) VALUES (?,?,?)",
                  (_h(token), user_id, db.now() + SESSION_DAYS * 86400))
    resp.set_cookie(COOKIE, token, max_age=SESSION_DAYS * 86400, httponly=True,
                    secure=COOKIE_SECURE, samesite="lax", path="/")


def current_user(req: Request) -> dict:
    token = req.cookies.get(COOKIE)
    if not token:
        raise HTTPException(401, "Please sign in.")
    s = db.one("SELECT user_id FROM sessions WHERE token_hash=? AND expires_at>?", _h(token), db.now())
    if not s:
        raise HTTPException(401, "Your session has ended. Please sign in again.")
    u = db.one("SELECT * FROM users WHERE id=?", s["user_id"])
    if not u:
        raise HTTPException(401, "Please sign in.")
    return u


def optional_user(req: Request) -> dict | None:
    try:
        return current_user(req)
    except HTTPException:
        return None


# ── Signup token (proves the phone was verified, valid 20 minutes) ──
def _signup_token(phone: str) -> str:
    exp = str(db.now() + 1200)
    return f"{phone}|{exp}|{_h('signup|' + phone + '|' + exp)}"


def _check_signup_token(tok: str) -> str:
    try:
        phone, exp, sig = tok.split("|")
    except ValueError:
        raise HTTPException(400, "Verification expired. Request a new code.")
    if not hmac.compare_digest(sig, _h("signup|" + phone + "|" + exp)) or int(exp) < db.now():
        raise HTTPException(400, "Verification expired. Request a new code.")
    return phone


# ── Endpoints ──
class OtpIn(BaseModel):
    phone: str = Field(max_length=20)


class VerifyIn(BaseModel):
    phone: str = Field(max_length=20)
    code: str = Field(pattern=r"^\d{4,6}$")


class RegisterIn(BaseModel):
    signup_token: str = Field(max_length=200)
    name: str = Field(min_length=2, max_length=120)
    dob: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    birth_time: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    city: str = Field(min_length=2, max_length=120)
    consent: bool
    whatsapp_optin: bool = False
    source: str | None = Field(default=None, max_length=40)


@router.post("/otp")
def request_otp(body: OtpIn):
    phone = normalise_phone(body.phone)
    today, t = date.today().isoformat(), db.now()
    prev = db.one("SELECT * FROM otps WHERE phone=?", phone)
    sends = 1
    if prev:
        if t - prev["sent_at"] < OTP_RESEND_GAP:
            raise HTTPException(429, f"Wait {OTP_RESEND_GAP - (t - prev['sent_at'])} seconds before asking for another code.")
        sends = prev["sends_today"] + 1 if prev["day"] == today else 1
        if sends > OTP_MAX_PER_DAY:
            raise HTTPException(429, "Too many codes requested today. Try again tomorrow.")
    code = f"{secrets.randbelow(10**6):06d}"
    send_sms_otp(phone, code)
    with db.tx() as c:
        c.execute("INSERT OR REPLACE INTO otps(phone, code_hash, expires_at, attempts, sent_at, sends_today, day) "
                  "VALUES (?,?,?,?,?,?,?)", (phone, _h(phone + code), t + OTP_TTL, 0, t, sends, today))
    return {"sent": True, "phone": phone, "dev_mode": OTP_DEV_MODE}


@router.post("/verify")
def verify_otp(body: VerifyIn, resp: Response):
    phone = normalise_phone(body.phone)
    o = db.one("SELECT * FROM otps WHERE phone=?", phone)
    if not o or o["expires_at"] < db.now():
        raise HTTPException(400, "That code has expired. Request a new one.")
    if o["attempts"] >= OTP_MAX_ATTEMPTS:
        raise HTTPException(429, "Too many wrong attempts. Request a new code.")
    if not hmac.compare_digest(o["code_hash"], _h(phone + body.code)):
        with db.tx() as c:
            c.execute("UPDATE otps SET attempts=attempts+1 WHERE phone=?", (phone,))
        raise HTTPException(400, "That code isn't right. Check it and try again.")
    with db.tx() as c:
        c.execute("DELETE FROM otps WHERE phone=?", (phone,))
    u = db.one("SELECT id FROM users WHERE phone=?", phone)
    if u:
        create_session(resp, u["id"])
        db.log_event(u["id"], "login")
        return {"ok": True, "needs_registration": False}
    return {"ok": True, "needs_registration": True, "signup_token": _signup_token(phone)}


@router.post("/register")
def register(body: RegisterIn, resp: Response):
    phone = _check_signup_token(body.signup_token)
    if not body.consent:
        raise HTTPException(422, "Please tick the consent box to continue.")
    try:
        born = date.fromisoformat(body.dob)
    except ValueError:
        raise HTTPException(422, "That date of birth doesn't exist. Check the day and month.")
    if born > date.today() or born.year < 1900:
        raise HTTPException(422, "Check your date of birth.")
    if body.birth_time:
        hh, mm = (int(x) for x in body.birth_time.split(":"))
        if hh > 23 or mm > 59:
            raise HTTPException(422, "Check your birth time.")
    if db.one("SELECT id FROM users WHERE phone=?", phone):
        raise HTTPException(409, "This number is already registered. Sign in instead.")
    src = re.sub(r"[^a-z0-9_-]", "", (body.source or "").lower())[:40] or None
    with db.tx() as c:
        cur = c.execute(
            "INSERT INTO users(phone, name, dob, birth_time, city, source, consent_at, consent_text, "
            "whatsapp_optin, free_questions_used, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (phone, body.name.strip(), body.dob, body.birth_time, body.city.strip(), src, db.now(),
             CONSENT_TEXT, int(body.whatsapp_optin), reports.questions_used_before(phone), db.now()))
        uid = cur.lastrowid
    create_session(resp, uid)
    db.log_event(uid, "register", {"source": src})
    return {"ok": True}


@router.post("/logout")
def logout(req: Request, resp: Response):
    token = req.cookies.get(COOKIE)
    if token:
        with db.tx() as c:
            c.execute("DELETE FROM sessions WHERE token_hash=?", (_h(token),))
    resp.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@router.get("/consent-text")
def consent_text():
    return {"text": CONSENT_TEXT}
