"""The core report (one free per phone number), add-on reports, and the open/locked split."""
from __future__ import annotations
import hashlib, hmac, json, os
from datetime import date

from fastapi import HTTPException

import db
import numerology

FREE_SECTIONS = ["simple_guidance", "overview", "life_path", "name_number", "chart_basics", "year_ahead"]
LOCKED_SECTIONS = ["soul_personality", "dasha_now", "career_money", "relationships",
                   "energy_mindset", "remedies_manifestation", "months_ahead"]
LANGS = ("en", "hi")
SECTION_TITLES = {
    "en": {
        "simple_guidance": "Your guidance, in simple words",
        "overview": "Who you are, at a glance",
        "life_path": "Your life's main theme (Life Path)",
        "name_number": "What your name says about you",
        "chart_basics": "Your birth chart, explained simply",
        "year_ahead": "What this year is about for you",
        "soul_personality": "What you truly want, and how others see you",
        "dasha_now": "The life chapter you are in now (Dasha)",
        "career_money": "Career and money",
        "relationships": "Love and relationships",
        "energy_mindset": "Energy, mind and daily habits",
        "remedies_manifestation": "Simple remedies and your daily manifestation practice",
        "months_ahead": "Your next 12 months, month by month",
    },
    "hi": {
        "simple_guidance": "आपके लिए मार्गदर्शन, आसान शब्दों में",
        "overview": "आप कौन हैं, एक नज़र में",
        "life_path": "आपके जीवन की मुख्य दिशा (लाइफ़ पाथ)",
        "name_number": "आपका नाम आपके बारे में क्या कहता है",
        "chart_basics": "आपकी जन्म कुंडली, आसान भाषा में",
        "year_ahead": "यह साल आपके लिए किस बारे में है",
        "soul_personality": "आप दिल से क्या चाहते हैं, और लोग आपको कैसे देखते हैं",
        "dasha_now": "जीवन का वह अध्याय जिसमें आप अभी हैं (दशा)",
        "career_money": "करियर और पैसा",
        "relationships": "प्यार और रिश्ते",
        "energy_mindset": "ऊर्जा, मन और रोज़ की आदतें",
        "remedies_manifestation": "आसान उपाय और आपकी रोज़ की मैनिफ़ेस्टेशन प्रैक्टिस",
        "months_ahead": "अगले 12 महीने, हर महीने का हाल",
    },
}

STYLE = {
    "en": """LANGUAGE AND STYLE (most important):
- Write for an ordinary person who has never studied astrology or numerology. Simple everyday English, short sentences (under 18 words), warm and encouraging, like a wise elder speaking to them.
- No jargon. If a term like Life Path, Dasha, Lagna, Nakshatra or Personal Year appears, explain it in plain words in the same sentence.
- Every section must end with something practical: what to do, what to avoid, or what to watch for.
- Never frighten. Never predict death, illness, accidents or divorce. Frame everything as tradition and guidance, not certainty.""",
    "hi": """भाषा और शैली (सबसे ज़रूरी):
- पूरी रिपोर्ट आसान, रोज़मर्रा की हिंदी (देवनागरी लिपि) में लिखें, जैसी आम लोग बोलते हैं। कठिन संस्कृत शब्दों से बचें। छोटे वाक्य। गर्मजोशी और हौसला देने वाला लहजा, जैसे कोई समझदार बड़ा भाई समझा रहा हो।
- कोई तकनीकी शब्द (लाइफ़ पाथ, दशा, लग्न, नक्षत्र, पर्सनल ईयर) आए तो उसी वाक्य में आसान शब्दों में उसका मतलब बताएँ।
- हर सेक्शन के अंत में कुछ व्यावहारिक हो: क्या करें, किससे बचें, किस बात का ध्यान रखें।
- कभी डराएँ नहीं। मृत्यु, बीमारी, दुर्घटना या तलाक़ की भविष्यवाणी कभी न करें। सब कुछ परंपरा और मार्गदर्शन के रूप में लिखें, निश्चित सच के रूप में नहीं।
- JSON की keys अंग्रेज़ी में ही रहें; सिर्फ़ values हिंदी में हों।""",
}


_SECRET = os.getenv("SESSION_SECRET", "dev-secret")


def phone_key(phone: str) -> str:
    """Keyed hash of the phone number, kept after account deletion only to stop the free
    report being claimed again by deleting and re-registering. It can't be reversed to the number."""
    return hmac.new(_SECRET.encode(), ("free|" + phone).encode(), hashlib.sha256).hexdigest()


def free_already_used(phone: str) -> bool:
    return bool(db.one("SELECT 1 FROM free_grants WHERE phone_key=? AND report_used=1", phone_key(phone)))


def questions_used_before(phone: str) -> int:
    r = db.one("SELECT questions_used FROM free_grants WHERE phone_key=?", phone_key(phone))
    return r["questions_used"] if r else 0


def remember_on_delete(phone: str, report_used: bool, questions_used: int):
    with db.tx() as c:
        c.execute("INSERT INTO free_grants(phone_key, at, report_used, questions_used) VALUES (?,?,?,?) "
                  "ON CONFLICT(phone_key) DO UPDATE SET report_used=MAX(report_used, excluded.report_used), "
                  "questions_used=MAX(questions_used, excluded.questions_used)",
                  (phone_key(phone), db.now(), int(report_used), questions_used))


def core_prompt(user: dict, nums: dict, chart_text: str, lang: str = "en") -> str:
    py, ch = nums["pythagorean"], nums["chaldean"]
    return f"""Write the complete Destiny OS core report for this person.

Name (as given at birth): {user['name']}
Date of birth: {user['dob']}  ·  Birth time: {user['birth_time'] or 'not known'}  ·  Birth city: {user['city']}
Pythagorean: Life Path {py['lifePath']}, Birth number {py['birthNumber']}, Expression {py['expressionCompound']}/{py['expression']}, Soul Urge {py['soulUrge']}, Personality {py['personality']}, Personal Year {py['personalYear']}
Chaldean: Expression {ch['expressionCompound']}/{ch['expression']}, Soul Urge {ch['soulUrge']}, Personality {ch['personality']}
{chart_text}
Manifestation goal they've shared: {user.get('manifest_goal') or 'none yet'}
Today: {date.today().isoformat()}

{STYLE.get(lang, STYLE['en'])}

Write specifically to THIS person, in the second person. Cross-check the two numerology systems and say simply where they agree. Use only the chart facts given; never invent planetary positions.
Reply with only JSON: {{"headline": string (under 12 words), "sections": {{
 "simple_guidance": string (7 short lines separated by newlines, each starting with "• ": 1) what kind of person you are in one line, 2) what this year is about, 3) your biggest strength to use now, 4) one thing to be careful about, 5) best days of the week and lucky colours, 6) one simple daily habit, 7) one encouraging closing line),
 "overview": string (80-110 words),
 "life_path": string (90-120 words),
 "name_number": string (80-110 words, simply compare the two systems),
 "chart_basics": string (90-120 words: Moon sign, nakshatra and lagna if known, each explained in plain words),
 "year_ahead": string (70-100 words on Personal Year {py['personalYear']}),
 "soul_personality": string (110-140 words),
 "dasha_now": string (130-170 words: which life chapter they are in, how long it lasts, what it asks of them),
 "career_money": string (130-170 words, practical; no specific investments),
 "relationships": string (110-140 words),
 "energy_mindset": string (110-140 words, evidence-based habits: sleep, focus, stress),
 "remedies_manifestation": string (130-170 words: simple traditional remedies framed as tradition, plus a 2-minute daily manifestation practice matched to their numbers and goal, with the exact words to say),
 "months_ahead": string (12 short lines separated by newlines, one per month starting next month, "Month YYYY: theme. One action.")
}}}}"""


def translate_prompt(data: dict, lang: str) -> str:
    src = {"headline": data.get("headline", ""), "sections": data.get("sections", {})}
    return f"""Rewrite this Destiny OS report in {'simple everyday Hindi (Devanagari script)' if lang == 'hi' else 'simple everyday English'}.
Keep the meaning, every fact and every number exactly; keep the same JSON keys and the line structure ("• " bullets, one line per month).
{STYLE.get(lang, STYLE['en'])}
Reply with only JSON in the same shape:
{json.dumps(src, ensure_ascii=False)}"""


def audio_script_prompt(data: dict, name: str, lang: str) -> str:
    sec = data.get("sections", {})
    return f"""Write a spoken voice briefing of about 230 words for {name.split()[0]}, to be read aloud in Dr. Krish Bharggav's voice.
Base it only on this report:
Headline: {data.get('headline', '')}
Guidance: {sec.get('simple_guidance', '')}
Overview: {sec.get('overview', '')}
This year: {sec.get('year_ahead', '')}

Rules: {'simple everyday Hindi in Devanagari script' if lang == 'hi' else 'simple everyday English'}; warm, personal, like a phone call from a wise elder brother; short spoken sentences; no bullet points, symbols, emojis or headings; numbers written as words.
Start by greeting them by first name and saying this is their Destiny OS voice briefing. End by inviting them to read the full report in their Destiny OS app, and say clearly that this message was created with Dr. Krish's AI voice.
Reply with only the script text."""


def _first_sentence(body: str) -> str:
    import re as _re
    first = _re.split(r"(?<=[.!?।])\s+", body.strip())[0] if body.strip() else ""
    first = first.lstrip("• ")[:120].rstrip(".,;। ")
    return (first + "…") if first else ""


def shape_core(data: dict, subscribed: bool) -> dict:
    lang = data.get("lang", "en") if data.get("lang") in LANGS else "en"
    titles = SECTION_TITLES[lang]
    out = {"headline": data.get("headline", ""), "numbers": data.get("numbers"), "lang": lang,
           "chart_brief": data.get("chart_brief"), "created_at": data.get("created_at"), "sections": []}
    sec = data.get("sections", {})
    for sid in FREE_SECTIONS + LOCKED_SECTIONS:
        if sid not in sec:
            continue                                      # reports made before a section existed
        body = str(sec.get(sid, "")).strip()
        locked = sid in LOCKED_SECTIONS and not subscribed
        if locked:
            out["sections"].append({"id": sid, "title": titles[sid], "locked": True, "teaser": _first_sentence(body)})
        else:
            out["sections"].append({"id": sid, "title": titles[sid], "locked": False, "body": body})
    return out


def compat_prompt(user: dict, me: dict, partner: dict, pnums: dict) -> str:
    return f"""Write a numerology compatibility report for two people.
Person A: {user['name']}, born {user['dob']}. Pythagorean Life Path {me['lifePath']}, Expression {me['expression']}, Soul Urge {me['soulUrge']}.
Person B: {partner['name']}, born {partner['dob']}. Pythagorean Life Path {pnums['lifePath']}, Expression {pnums['expression']}, Soul Urge {pnums['soulUrge']}.
Relationship type: {partner.get('relation') or 'partner'}.
Be balanced and kind; never say a pairing is doomed. Practical ways to work together.
Reply with only JSON: {{"headline": string, "score": integer 1-10 (traditional harmony of the numbers), "sections": {{"how_you_connect": string, "strengths": string, "friction_points": string, "how_to_make_it_work": string}}}}"""


def annual_prompt(user: dict, nums: dict, chart_text: str, year: int) -> str:
    return f"""Write a 12-month forecast for {user['name']} (born {user['dob']}) for {year}.
Pythagorean Life Path {nums['lifePath']}, Personal Year for {year}: {numerology.calc(user['name'], user['dob'], 'pyth', date(year, 6, 1))['personalYear']}.
{chart_text}
Frame astrology as tradition. Practical, specific, no guarantees, no investment picks.
Reply with only JSON: {{"headline": string, "year_theme": string (120 words), "months": [{{"month": "January {year}", "personal_month": integer, "theme": string, "focus": string, "caution": string}}] (12 items), "best_windows": string (dates or months good for launches, signing and travel)}}"""


def save_report(user_id: int, kind: str, data: dict) -> int:
    with db.tx() as c:
        cur = c.execute("INSERT INTO reports(user_id, kind, data, created_at) VALUES (?,?,?,?)",
                        (user_id, kind, json.dumps(data), db.now()))
        return cur.lastrowid


def grant_free(phone: str):
    with db.tx() as c:
        c.execute("INSERT INTO free_grants(phone_key, at, report_used) VALUES (?,?,1) "
                  "ON CONFLICT(phone_key) DO UPDATE SET report_used=1", (phone_key(phone), db.now()))


def get_core(user_id: int, lang: str | None = None) -> dict | None:
    """The user's core report, preferring the requested language. Adds its row id as '_id'."""
    rows = db.all_("SELECT id, data FROM reports WHERE user_id=? AND kind='core' ORDER BY created_at DESC, id DESC", user_id)
    if not rows:
        return None
    parsed = [(r["id"], json.loads(r["data"])) for r in rows]
    if lang:
        for rid, d in parsed:
            if d.get("lang", "en") == lang:
                return {**d, "_id": rid}
    rid, d = parsed[0]
    return {**d, "_id": rid}


def update_report(report_id: int, data: dict):
    data = {k: v for k, v in data.items() if k != "_id"}
    with db.tx() as c:
        c.execute("UPDATE reports SET data=? WHERE id=?", (json.dumps(data), report_id))


def require_kind(kind: str):
    if kind not in ("compatibility", "annual"):
        raise HTTPException(404, "Unknown report.")
