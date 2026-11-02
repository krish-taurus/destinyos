"""Destiny OS beta API — FastAPI on Render/Railway."""
from __future__ import annotations
import base64, hashlib, json, os, re, time
from collections import defaultdict, deque
from datetime import date
from functools import lru_cache

import httpx
from anthropic import Anthropic
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from timezonefinder import TimezoneFinder

from astro import build_chart

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
app = FastAPI(title="Destiny OS API", version="0.1-beta")
app.add_middleware(CORSMiddleware, allow_origins=ORIGINS, allow_methods=["GET", "POST"],
                   allow_headers=["*"])

# ── Rate limiting (in-memory; move to Redis when you scale past one instance) ──
LIMITS = {"chart": (30, 3600), "brief": (20, 3600), "ask": (40, 3600),
          "food": (15, 3600), "compass": (6, 3600)}
_hits: dict[tuple[str, str], deque] = defaultdict(deque)


def limit(req: Request, bucket: str):
    ip = req.headers.get("x-forwarded-for", req.client.host if req.client else "?").split(",")[0]
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


# ── Models ──
class ChartIn(BaseModel):
    dob: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    time: str | None = None
    city: str = Field(min_length=2, max_length=120)


class Profile(BaseModel):
    name: str = Field(max_length=120)
    numerology: dict
    chart: dict | None = None
    meals: list[dict] = []
    context: dict | None = None


class AskIn(BaseModel):
    profile: Profile
    turns: list[dict] = Field(max_length=14)


def profile_text(p: Profile) -> str:
    n = p.numerology
    meals = "; ".join(f"{m.get('name')} ~{m.get('kcal')} kcal" for m in p.meals[-8:]) or "none"
    return (f"Name: {p.name}\nNumerology: Life Path {n.get('lifePath')}, Expression {n.get('expression')}, "
            f"Soul Urge {n.get('soulUrge')}, Personal Year {n.get('personalYear')}, Personal Month "
            f"{n.get('personalMonth')}, Personal Day {n.get('personalDay')}\n{chart_summary(p.chart)}\n"
            f"Biometrics: no device connected\nMeals logged today: {meals}\nToday: {date.today().isoformat()}")


# ── Endpoints ──
@app.get("/api/health")
def health():
    return {"ok": True}


@app.post("/api/chart")
def chart(body: ChartIn, req: Request):
    limit(req, "chart")
    lat, lon, tz = geocode(body.city)
    try:
        c = build_chart(body.dob, body.time, lat, lon, tz)
    except Exception as e:
        raise HTTPException(422, "Couldn't compute the chart from those details.") from e
    c["place"] = {"city": body.city, "lat": lat, "lon": lon, "tz": tz}
    return c


_brief_cache: dict[str, dict] = {}


@app.post("/api/brief")
def brief(p: Profile, req: Request):
    key = hashlib.sha256((profile_text(p)).encode()).hexdigest()
    if key in _brief_cache:
        return _brief_cache[key]
    limit(req, "brief")
    system = f"You are the daily-brief engine of Destiny OS.\n{GUARDRAILS}"
    prompt = f"""Build today's guidance for this person.
{profile_text(p)}

Reply with only JSON:
{{"astro_headline": string (the single most relevant transit or dasha theme today, under 10 words),
 "astro_detail": string (2 sentences),
 "numerology_note": string (1–2 sentences on Personal Day {p.numerology.get('personalDay')}),
 "psychology_tip": string (1–2 sentences, evidence-based: sleep, focus, habits, CBT),
 "decisions": [{{"type": "go"|"pause"|"stop", "text": string, "why": string}}] (exactly 3, one of each type, generic enough to apply to most people's day unless context says otherwise),
 "wear": [{{"name": string, "hex": string}}] (3–4 colours),
 "avoid": [{{"name": string, "hex": string}}] (2–3 colours),
 "extra": string (one line: direction, gemstone or ritual, framed as tradition)}}"""
    out = parse_json(ask_claude(system, [{"role": "user", "content": prompt}]))
    _brief_cache[key] = out
    return out


@app.post("/api/ask")
def ask(body: AskIn, req: Request):
    limit(req, "ask")
    turns = [t for t in body.turns if t.get("role") in ("user", "assistant") and t.get("content")][-12:]
    if not turns or turns[-1]["role"] != "user":
        raise HTTPException(422, "Send a message first.")
    system = (f"You are Destiny OS, a guidance companion on WhatsApp blending Vedic astrology, numerology, "
              f"colour tradition, evidence-based psychology and behavioural science. Reply under 150 words, "
              f"WhatsApp style, *bold* for key terms, sparing emojis, one concrete recommendation.\n{GUARDRAILS}\n\n"
              f"User profile:\n{profile_text(body.profile)}")
    msgs = [{"role": t["role"], "content": str(t["content"])[:2000]} for t in turns]
    return {"reply": ask_claude(system, msgs, model=FAST_MODEL, max_tokens=600)}


@app.post("/api/food")
async def food(req: Request, image: UploadFile = File(...), hint: str = Form(""), profile: str = Form("{}")):
    limit(req, "food")
    media = image.content_type or ""
    if media not in ("image/jpeg", "image/png", "image/webp", "image/gif"):
        raise HTTPException(415, "Use a JPEG, PNG or WebP photo.")
    data = await image.read()
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(413, "Photo is over 5 MB. The app shrinks photos automatically — try again.")
    try:
        prof = Profile(**json.loads(profile))
        ptxt = profile_text(prof)
    except Exception:
        ptxt = "No profile."
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


@app.post("/api/compass")
def compass(p: Profile, req: Request):
    limit(req, "compass")
    ctx = json.dumps(p.context or {}, ensure_ascii=False)[:2000]
    prompt = f"""Build a personalised 30-day plan across five pillars: body, mind, money, relationships, purpose.
Profile:
{profile_text(p)}
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
