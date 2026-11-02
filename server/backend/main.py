"""Destiny OS API — accounts, free report, Destiny Plus subscription, and the guidance engines."""
from __future__ import annotations
import base64, hashlib, json, logging, os, re, time
from collections import defaultdict, deque
from datetime import date
from functools import lru_cache

import httpx
from anthropic import Anthropic
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from timezonefinder import TimezoneFinder

from astro import build_chart
import db, numerology, reports
import auth, billing
from auth import current_user
from billing import is_subscriber, require_subscriber, plan_status

MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-5")
FAST_MODEL = os.getenv("CLAUDE_FAST_MODEL", "claude-haiku-4-5-20251001")
ORIGINS = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(",")]

# Kimi (Moonshot AI) as a stand-in while the Anthropic account is out of
# credit — set only, never required. OpenAI-compatible chat/completions.
KIMI_API_KEY = os.getenv("KIMI_API_KEY", "")
KIMI_BASE_URL = os.getenv("KIMI_BASE_URL", "https://api.moonshot.ai/v1")
KIMI_MODEL = os.getenv("KIMI_MODEL", "kimi-latest")
KIMI_FAST_MODEL = os.getenv("KIMI_FAST_MODEL", KIMI_MODEL)

client = Anthropic()  # reads ANTHROPIC_API_KEY
tzf = TimezoneFinder()
app = FastAPI(title="Destiny OS API", version="1.0")
logging.basicConfig(level=logging.INFO)
app.include_router(auth.router)
app.include_router(billing.router)
app.add_middleware(CORSMiddleware, allow_origins=ORIGINS, allow_methods=["GET", "POST", "PATCH", "DELETE"], allow_credentials=True,
                   allow_headers=["*"])

# ── Rate limiting (in-memory; move to Redis when you scale past one instance) ──
LIMITS = {"chart": (30, 3600), "brief": (20, 3600), "ask": (40, 3600),
          "food": (15, 3600), "compass": (6, 3600), "otp": (10, 3600), "report": (6, 3600)}
_hits: dict[tuple[str, str], deque] = defaultdict(deque)


def limit(req: Request, bucket: str):
    # uvicorn --proxy-headers already resolves the real client IP behind nginx (127.0.0.1 is the trusted proxy);
    # never read X-Forwarded-For directly: its first entry is whatever the client sent.
    ip = req.client.host if req.client else "?"
    n, window = LIMITS[bucket]
    q, now = _hits[(ip, bucket)], time.time()
    while q and q[0] < now - window:
        q.popleft()
    if len(q) >= n:
        raise HTTPException(429, "Too many requests. Try again in a little while.")
    q.append(now)


# ── Geocoding ──
CITIES = {
    "bengaluru": (12.9716, 77.5946), "bangalore": (12.9716, 77.5946), "mumbai": (19.076, 72.8777),
    "delhi": (28.6139, 77.209), "new delhi": (28.6139, 77.209), "chennai": (13.0827, 80.2707),
    "hyderabad": (17.385, 78.4867), "kolkata": (22.5726, 88.3639), "pune": (18.5204, 73.8567),
    "ahmedabad": (23.0225, 72.5714), "jaipur": (26.9124, 75.7873), "lucknow": (26.8467, 80.9462),
    "kochi": (9.9312, 76.2673), "mysuru": (12.2958, 76.6394), "mysore": (12.2958, 76.6394),
    "coimbatore": (11.0168, 76.9558), "varanasi": (25.3176, 82.9739), "patna": (25.5941, 85.1376),
    "london": (51.5074, -0.1278), "dubai": (25.2048, 55.2708), "singapore": (1.3521, 103.8198),
    "new york": (40.7128, -74.006), "manila": (14.5995, 120.9842), "lagos": (6.5244, 3.3792),
    "nairobi": (-1.2921, 36.8219), "johannesburg": (-26.2041, 28.0473),
}


@lru_cache(maxsize=2048)
def geocode(city: str) -> tuple[float, float, str]:
    key = city.lower().split(",")[0].strip()
    if key in CITIES:
        lat, lon = CITIES[key]
    else:
        r = httpx.get("https://nominatim.openstreetmap.org/search",
                      params={"q": city, "format": "json", "limit": 1},
                      headers={"User-Agent": "DestinyOS/0.1 (contact@browsejobs.ai)"}, timeout=10)
        data = r.json()
        if not data:
            raise HTTPException(422, f"Couldn't find '{city}'. Try 'City, Country'.")
        lat, lon = float(data[0]["lat"]), float(data[0]["lon"])
    return lat, lon, tzf.timezone_at(lat=lat, lng=lon) or "UTC"


# ── Claude helpers ──
GUARDRAILS = """Frame astrology and numerology as tradition ("in Jyotish, this transit is associated with…"), never as guaranteed fact.
Never name specific stocks, funds or crypto; for investments suggest a SEBI-registered adviser.
Never diagnose; for health red flags, advise seeing a doctor. No calorie targets under 1500, no crash diets, no moralising about food.
English only. Be specific and practical, never vague."""


def _has_image(messages: list) -> bool:
    """True if any message carries an Anthropic-style image content block
    (Food Lens). Kimi's request shape isn't wired up for that here, so those
    calls always go to Claude — everything else (brief, ask, compass, all
    plain text) can use either."""
    for m in messages:
        content = m.get("content")
        if isinstance(content, list):
            if any(isinstance(b, dict) and b.get("type") == "image" for b in content):
                return True
    return False


def ask_kimi(system: str, messages: list, model: str, max_tokens: int) -> str:
    chat_messages = [{"role": "system", "content": system}]
    chat_messages += [{"role": m["role"], "content": m["content"]} for m in messages]
    # These Kimi models reason before answering, and that reasoning alone
    # burns several hundred tokens even for a trivial prompt (measured:
    # ~500 tokens of reasoning for "say hello in 5 words") — Claude's own
    # tuned budgets (600–3000) leave no room left for the actual reply once
    # spent on that. A generous floor here, not touched for the Claude path.
    kimi_max_tokens = max(max_tokens * 3, 3000)
    r = httpx.post(
        f"{KIMI_BASE_URL.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {KIMI_API_KEY}"},
        json={"model": model, "max_tokens": kimi_max_tokens, "messages": chat_messages},
        timeout=180,
    )
    r.raise_for_status()
    content = r.json()["choices"][0]["message"]["content"].strip()
    if not content:
        raise ValueError("Kimi returned no content (reasoning likely used the whole budget).")
    return content


def ask_claude(system: str, messages: list, model: str = MODEL, max_tokens: int = 1500) -> str:
    # Prefer Kimi when a key is set (stand-in while Anthropic credits are
    # topped up) — silently falls through to Claude if Kimi errors, so a bad
    # Kimi key/outage doesn't take the whole app down.
    if KIMI_API_KEY and not _has_image(messages):
        try:
            kimi_model = KIMI_FAST_MODEL if model == FAST_MODEL else KIMI_MODEL
            return ask_kimi(system, messages, kimi_model, max_tokens)
        except Exception:
            pass
    try:
        r = client.messages.create(model=model, max_tokens=max_tokens, system=system, messages=messages)
    except Exception as e:  # surface a clean error to the client
        raise HTTPException(502, "The guidance engine is unavailable right now. Try again shortly.") from e
    return "".join(b.text for b in r.content if b.type == "text").strip()


def parse_json(text: str):
    t = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        m = re.search(r"[\{\[].*[\}\]]", t, re.S)
        if m:
            return json.loads(m.group(0))
        raise HTTPException(502, "The answer came back in the wrong format. Try again.")


def chart_summary(c: dict | None) -> str:
    if not c:
        return "Chart not available."
    d = c["dasha"]
    lines = [f"Lagna: {c['lagna']['sign'] if c.get('lagna') else 'unknown (no birth time)'}",
             f"Natal Moon: {c['natal']['Moon']['sign']} ({c['natal']['Moon']['nakshatra']}), Sun: {c['natal']['Sun']['sign']}",
             f"Mahadasha: {d['mahadasha']['lord']} ({d['mahadasha']['start']} to {d['mahadasha']['end']}), "
             f"Antardasha: {d['antardasha']['lord'] if d['antardasha'] else '?'}",
             "Today's transits (sign, house from natal Moon): " + ", ".join(
                 f"{k} {v['sign']} H{v['house_from_moon']}{' R' if v.get('retrograde') else ''}"
                 for k, v in c["transits"].items()),
             f"Moon today: {c['moon_today']['sign']} in {c['moon_today']['nakshatra']}"]
    return "\n".join(lines)


# ── Per-IP limits on the public auth endpoints (SMS costs money) ──
@app.middleware("http")
async def _otp_ip_limit(req: Request, call_next):
    if req.method == "POST" and req.url.path == "/api/auth/otp":
        try:
            limit(req, "otp")
        except HTTPException as e:
            from fastapi.responses import JSONResponse
            return JSONResponse({"detail": e.detail}, status_code=e.status_code)
    return await call_next(req)


FREE_QUESTIONS = int(os.getenv("FREE_QUESTIONS", "3"))      # lifetime taster for free users
DAILY_QUESTIONS = int(os.getenv("DAILY_QUESTIONS", "30"))   # fair use for Destiny Plus


# ── Server-side profile (built from the account, never trusted from the browser) ──
_chart_cache: dict[tuple[int, str], dict] = {}


def user_chart(u: dict) -> dict | None:
    key = (u["id"], date.today().isoformat())
    if key not in _chart_cache:
        try:
            lat, lon, tz = geocode(u["city"])
            c = build_chart(u["dob"], u["birth_time"], lat, lon, tz)
            c["place"] = {"city": u["city"], "lat": lat, "lon": lon, "tz": tz}
            _chart_cache[key] = c
        except Exception:
            logging.exception("chart failed for user %s", u["id"])
            return None
    return _chart_cache[key]


def slim_chart(c: dict | None) -> dict | None:
    if not c:
        return None
    return {k: c.get(k) for k in ("time_known", "lagna", "natal", "dasha", "transits", "moon_today", "notes", "place")}


def profile_text_for(u: dict, meals: list[dict] | None = None, chart: dict | None = None) -> str:
    n = numerology.calc(u["name"], u["dob"], "pyth")
    meals_txt = "; ".join(f"{m.get('name')} ~{m.get('kcal')} kcal" for m in (meals or [])[-8:]) or "none"
    return (f"Name: {u['name']}\nNumerology (Pythagorean): Life Path {n['lifePath']}, Expression {n['expression']}, "
            f"Soul Urge {n['soulUrge']}, Personal Year {n['personalYear']}, Personal Month {n['personalMonth']}, "
            f"Personal Day {n['personalDay']}\n{chart_summary(chart if chart is not None else user_chart(u))}\n"
            f"Manifestation goal: {u.get('manifest_goal') or 'not set'}\n"
            f"Biometrics: no device connected\nMeals logged today: {meals_txt}\nToday: {date.today().isoformat()}")


def bump_usage(user_id: int, bucket: str) -> int:
    day = date.today().isoformat()
    with db.tx() as c:
        c.execute("INSERT INTO usage(user_id, day, bucket, n) VALUES (?,?,?,1) "
                  "ON CONFLICT(user_id, day, bucket) DO UPDATE SET n=n+1", (user_id, day, bucket))
    return db.one("SELECT n FROM usage WHERE user_id=? AND day=? AND bucket=?", user_id, day, bucket)["n"]


def usage_today(user_id: int, bucket: str) -> int:
    r = db.one("SELECT n FROM usage WHERE user_id=? AND day=? AND bucket=?", user_id, date.today().isoformat(), bucket)
    return r["n"] if r else 0


def reserve_question(u: dict) -> str:
    """Count the question BEFORE answering, inside one locked transaction."""
    day = date.today().isoformat()
    with db.tx() as c:
        if is_subscriber(u["id"]):
            c.execute("INSERT OR IGNORE INTO usage(user_id, day, bucket, n) VALUES (?,?,'ask',0)", (u["id"], day))
            cur = c.execute("UPDATE usage SET n=n+1 WHERE user_id=? AND day=? AND bucket='ask' AND n<?",
                            (u["id"], day, DAILY_QUESTIONS))
            if cur.rowcount == 0:
                raise HTTPException(429, f"You've reached today's fair-use limit of {DAILY_QUESTIONS} questions. It resets at midnight.")
            return "daily"
        cur = c.execute("UPDATE users SET free_questions_used=free_questions_used+1 WHERE id=? AND free_questions_used<?",
                        (u["id"], FREE_QUESTIONS))
        if cur.rowcount == 0:
            raise HTTPException(402, f"You've used your {FREE_QUESTIONS} free questions. Subscribe to Destiny Plus to ask as many as you like.")
        return "free"


def release_question(user_id: int, kind: str):
    with db.tx() as c:
        if kind == "daily":
            c.execute("UPDATE usage SET n=MAX(n-1,0) WHERE user_id=? AND day=? AND bucket='ask'", (user_id, date.today().isoformat()))
        else:
            c.execute("UPDATE users SET free_questions_used=MAX(free_questions_used-1,0) WHERE id=?", (user_id,))


def questions_left(u: dict) -> dict:
    if is_subscriber(u["id"]):
        return {"kind": "daily", "left": max(0, DAILY_QUESTIONS - usage_today(u["id"], "ask")), "of": DAILY_QUESTIONS}
    return {"kind": "free", "left": max(0, FREE_QUESTIONS - u["free_questions_used"]), "of": FREE_QUESTIONS}


# ── Endpoints ──
@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/me")
def me(u=Depends(current_user)):
    has_core = bool(db.one("SELECT 1 FROM reports WHERE user_id=? AND kind='core'", u["id"]))
    return {"name": u["name"], "phone": u["phone"], "dob": u["dob"], "birth_time": u["birth_time"], "city": u["city"],
            "whatsapp_optin": bool(u["whatsapp_optin"]), "manifest_goal": u["manifest_goal"],
            "numerology": numerology.both(u["name"], u["dob"]),
            "has_report": has_core, "free_report_available": not has_core and not reports.free_already_used(u["phone"]),
            "questions": questions_left(u), "plan": plan_status(u["id"]),
            "consultation_whatsapp": "https://wa.me/917975554666"}


class MePatch(BaseModel):
    manifest_goal: str | None = Field(default=None, max_length=300)
    whatsapp_optin: bool | None = None


@app.patch("/api/me")
def me_patch(body: MePatch, u=Depends(current_user)):
    with db.tx() as c:
        if body.manifest_goal is not None:
            c.execute("UPDATE users SET manifest_goal=? WHERE id=?", (body.manifest_goal.strip() or None, u["id"]))
        if body.whatsapp_optin is not None:
            c.execute("UPDATE users SET whatsapp_optin=? WHERE id=?", (int(body.whatsapp_optin), u["id"]))
    return {"ok": True}


@app.delete("/api/me")
def me_delete(req: Request, u=Depends(current_user)):
    """DPDP right to erasure: cancels any subscription at once and deletes the account and all its data."""
    s = billing.subscription(u["id"])
    if s and s["status"] not in ("cancelled", "completed") and billing.configured():
        try:
            billing._rzp("POST", f"/subscriptions/{s['provider_sub_id']}/cancel", json={"cancel_at_cycle_end": 0})
        except HTTPException:
            raise HTTPException(502, "We couldn't cancel your subscription just now, so nothing was deleted. Try again in a minute.")
    had_report = bool(db.one("SELECT 1 FROM reports WHERE user_id=? AND kind='core'", u["id"]))
    # keep only a non-reversible marker so the free report and free questions can't be re-claimed
    reports.remember_on_delete(u["phone"], had_report, u["free_questions_used"])
    for k in [k for k in _chart_cache if k[0] == u["id"]]:
        _chart_cache.pop(k, None)
    with db.tx() as c:
        c.execute("DELETE FROM users WHERE id=?", (u["id"],))
        c.execute("DELETE FROM events WHERE user_id=?", (u["id"],))
        c.execute("DELETE FROM whatsapp_log WHERE user_id=?", (u["id"],))
    return {"ok": True}


# ── Core report: one free per phone number; locked sections need Destiny Plus ──
@app.post("/api/report")
def report_create(req: Request, u=Depends(current_user)):
    existing = reports.get_core(u["id"])
    sub = is_subscriber(u["id"])
    if existing:
        return reports.shape_core(existing, sub)
    if not sub and reports.free_already_used(u["phone"]):
        raise HTTPException(402, "A free report has already been created for this number. Subscribe to Destiny Plus to get your full report.")
    limit(req, "report")
    nums = numerology.both(u["name"], u["dob"])
    chart = user_chart(u)
    out = parse_json(ask_claude(f"You are the report writer of Destiny OS.\n{GUARDRAILS}",
                                [{"role": "user", "content": reports.core_prompt(u, nums, chart_summary(chart))}],
                                max_tokens=4000))
    if not isinstance(out, dict) or not isinstance(out.get("sections"), dict):
        raise HTTPException(502, "The report came back incomplete. Please try again.")
    out["numbers"] = nums
    out["chart_brief"] = slim_chart(chart)
    out["created_at"] = db.now()
    reports.save_report(u["id"], "core", out)
    reports.grant_free(u["phone"])
    db.log_event(u["id"], "report_core", {"subscribed": sub})
    return reports.shape_core(out, sub)


@app.get("/api/report")
def report_get(u=Depends(current_user)):
    r = reports.get_core(u["id"])
    if not r:
        raise HTTPException(404, "No report yet.")
    return reports.shape_core(r, is_subscriber(u["id"]))


# ── Add-on reports (after payment) ──
@app.post("/api/addon/{purchase_id}/generate")
def addon_generate(purchase_id: int, req: Request, u=Depends(current_user)):
    p = db.one("SELECT * FROM purchases WHERE id=? AND user_id=?", purchase_id, u["id"])
    if not p or p["status"] == "created":
        raise HTTPException(402, "This purchase isn't paid yet.")
    if p["item"] == "consultation":
        return {"kind": "consultation", "whatsapp": "https://wa.me/917975554666?text=" +
                f"Hi, I've booked a consultation (order {p['provider_order_id']}). When can we schedule it?"}
    reports.require_kind(p["item"])
    done = db.one("SELECT data FROM reports WHERE user_id=? AND kind=? AND created_at>=? ORDER BY created_at DESC LIMIT 1",
                  u["id"], p["item"], p["created_at"])
    if done and p["status"] == "fulfilled":
        return {"kind": p["item"], **json.loads(done["data"])}
    limit(req, "report")
    me_n = numerology.calc(u["name"], u["dob"])
    if p["item"] == "compatibility":
        d = json.loads(p["details"] or "{}")
        partner = {"name": str(d.get("name", ""))[:120], "dob": str(d.get("dob", ""))[:10], "relation": str(d.get("relation", ""))[:40]}
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", partner["dob"]):
            raise HTTPException(422, "Partner's date of birth is missing.")
        prompt = reports.compat_prompt(u, me_n, partner, numerology.calc(partner["name"], partner["dob"]))
        out = parse_json(ask_claude(f"You are the compatibility writer of Destiny OS.\n{GUARDRAILS}",
                                    [{"role": "user", "content": prompt}], max_tokens=2500))
        out["partner"] = partner["name"]
    else:
        year = date.today().year + (1 if date.today().month >= 11 else 0)
        out = parse_json(ask_claude(f"You are the forecast writer of Destiny OS.\n{GUARDRAILS}",
                                    [{"role": "user", "content": reports.annual_prompt(u, me_n, chart_summary(user_chart(u)), year)}],
                                    max_tokens=4000))
        out["year"] = year
    reports.save_report(u["id"], p["item"], out)
    with db.tx() as c:
        c.execute("UPDATE purchases SET status='fulfilled' WHERE id=?", (p["id"],))
    return {"kind": p["item"], **out}


@app.get("/api/addon/reports")
def addon_reports(u=Depends(current_user)):
    rows = db.all_("SELECT id, kind, data, created_at FROM reports WHERE user_id=? AND kind!='core' ORDER BY created_at DESC", u["id"])
    return {"reports": [{"id": r["id"], "kind": r["kind"], "created_at": r["created_at"], **json.loads(r["data"])} for r in rows]}


# ── Chart (signed-in users) ──
@app.get("/api/chart")
def chart(u=Depends(current_user)):
    c = user_chart(u)
    if not c:
        raise HTTPException(422, "Couldn't compute your chart from those details. Check your birth city.")
    return slim_chart(c)


# ── Destiny Plus features ──
class MealsIn(BaseModel):
    meals: list[dict] = Field(default=[], max_length=20)


_brief_cache: dict[str, dict] = {}


@app.post("/api/brief")
def brief(body: MealsIn, req: Request, u=Depends(require_subscriber)):
    ptxt = profile_text_for(u, body.meals)
    key = hashlib.sha256(ptxt.encode()).hexdigest()
    if key in _brief_cache:
        return _brief_cache[key]
    limit(req, "brief")
    pd = numerology.calc(u["name"], u["dob"])["personalDay"]
    system = f"You are the daily-brief engine of Destiny OS.\n{GUARDRAILS}"
    prompt = f"""Build today's guidance for this person.
{ptxt}

Reply with only JSON:
{{"astro_headline": string (the single most relevant transit or dasha theme today, under 10 words),
 "astro_detail": string (2 sentences),
 "numerology_note": string (1–2 sentences on Personal Day {pd}),
 "psychology_tip": string (1–2 sentences, evidence-based: sleep, focus, habits, CBT),
 "manifestation": string (a 2-minute practice for today matched to Personal Day {pd} and their goal if set, with the exact words to write or say),
 "decisions": [{{"type": "go"|"pause"|"stop", "text": string, "why": string}}] (exactly 3, one of each type),
 "wear": [{{"name": string, "hex": string}}] (3–4 colours),
 "avoid": [{{"name": string, "hex": string}}] (2–3 colours),
 "extra": string (one line: direction, gemstone or ritual, framed as tradition)}}"""
    out = parse_json(ask_claude(system, [{"role": "user", "content": prompt}]))
    _brief_cache[key] = out
    return out


class AskIn(BaseModel):
    turns: list[dict] = Field(max_length=14)
    meals: list[dict] = Field(default=[], max_length=20)


@app.post("/api/ask")
def ask(body: AskIn, req: Request, u=Depends(current_user)):
    limit(req, "ask")
    turns = [t for t in body.turns if t.get("role") in ("user", "assistant") and t.get("content")][-12:]
    if not turns or turns[-1]["role"] != "user":
        raise HTTPException(422, "Send a message first.")
    kind = reserve_question(u)            # atomic: parallel requests can't exceed the allowance
    system = (f"You are Destiny OS, a guidance companion blending Vedic astrology, numerology, colour tradition, "
              f"evidence-based psychology and behavioural science. Reply under 150 words, WhatsApp style, *bold* for "
              f"key terms, sparing emojis, one concrete recommendation.\n{GUARDRAILS}\n"
              f"If the person mentions self-harm, suicide, abuse or a crisis, do not give a reading: respond with care, "
              f"encourage them to contact Tele-MANAS (14416, free, 24x7) or emergency services (112), and a trusted person.\n\n"
              f"User profile:\n{profile_text_for(u, body.meals)}")
    msgs = [{"role": t["role"], "content": str(t["content"])[:2000]} for t in turns]
    try:
        reply = ask_claude(system, msgs, model=FAST_MODEL, max_tokens=600)
    except Exception:
        release_question(u["id"], kind)   # don't charge a question for our failure
        raise
    fresh = db.one("SELECT * FROM users WHERE id=?", u["id"])
    return {"reply": reply, "questions": questions_left(fresh)}


@app.post("/api/food")
async def food(req: Request, image: UploadFile = File(...), hint: str = Form(""), meals: str = Form("[]"),
               u=Depends(require_subscriber)):
    limit(req, "food")
    media = image.content_type or ""
    if media not in ("image/jpeg", "image/png", "image/webp", "image/gif"):
        raise HTTPException(415, "Use a JPEG, PNG or WebP photo.")
    data = await image.read()
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(413, "Photo is over 5 MB. The app shrinks photos automatically — try again.")
    try:
        ptxt = profile_text_for(u, json.loads(meals)[:20])
    except Exception:
        ptxt = profile_text_for(u)
    prompt = f"""The photo is a meal the user is about to eat. Identify each item (Indian dishes are common), estimate portions in grams or household units, and estimate calories and macros.
{('User note: ' + hint[:300]) if hint else ''}
User context:
{ptxt}
Reply with only JSON:
{{"meal_name": string, "items": [{{"name": string, "portion": string, "kcal": number}}], "kcal_low": number, "kcal_high": number, "kcal_best": number, "protein_g": number, "carbs_g": number, "fat_g": number, "fibre_g": number, "confidence": "low"|"medium"|"high", "advice": string}}
"advice": 2–3 practical sentences on how this meal fits their day. If the image is not food, return items as [] and say so in advice."""
    content = [{"type": "image", "source": {"type": "base64", "media_type": media,
                                            "data": base64.b64encode(data).decode()}},
               {"type": "text", "text": prompt}]
    return parse_json(ask_claude(f"You are the Food Lens of Destiny OS.\n{GUARDRAILS}",
                                 [{"role": "user", "content": content}]))


class CompassIn(BaseModel):
    context: dict | None = None


@app.post("/api/compass")
def compass(body: CompassIn, req: Request, u=Depends(require_subscriber)):
    limit(req, "compass")
    ctx = json.dumps(body.context or {}, ensure_ascii=False)[:2000]
    prompt = f"""Build a personalised 30-day plan across five pillars: body, mind, money, relationships, purpose.
Profile:
{profile_text_for(u)}
What they told us: {ctx}

Personalise to THIS person's goal, work, energy, sleep, worries, numbers and dasha. No generic filler.
Label each recommendation "evidence" (published research), "classical" (Jyotish/numerology tradition) or "symbolic" (reflective practice).
Money = where to focus effort and time, income skills, spending habits, emergency fund, timing of launches or negotiations. No specific investments.
Each pillar: 3–4 items, each a concrete action (what, when, how often) plus a one-sentence why.
focus: 1–10 per pillar for how much attention it needs this month.
Reply with only JSON:
{{"headline": string, "focus": {{"body": n, "mind": n, "money": n, "relationships": n, "purpose": n}},
 "pillars": {{"body": [{{"title": string, "why": string, "kind": "evidence"|"classical"|"symbolic"}}], "mind": [], "money": [], "relationships": [], "purpose": []}}}}"""
    return parse_json(ask_claude(f"You are the Life Compass engine of Destiny OS.\n{GUARDRAILS}",
                                 [{"role": "user", "content": prompt}], max_tokens=3000))
