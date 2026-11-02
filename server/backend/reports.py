"""The core report (one free per phone number), add-on reports, and the open/locked split."""
from __future__ import annotations
import hashlib, hmac, json, os
from datetime import date

from fastapi import HTTPException

import db
import numerology

FREE_SECTIONS = ["overview", "life_path", "name_number", "chart_basics", "year_ahead"]
LOCKED_SECTIONS = ["soul_personality", "dasha_now", "career_money", "relationships",
                   "energy_mindset", "remedies_manifestation", "months_ahead"]
SECTION_TITLES = {
    "overview": "Your blueprint at a glance",
    "life_path": "Your Life Path",
    "name_number": "Your name number, in both systems",
    "chart_basics": "Your Vedic chart: Moon, Lagna and Nakshatra",
    "year_ahead": "Your Personal Year",
    "soul_personality": "Soul Urge and Personality",
    "dasha_now": "Your current Dasha, and what it is asking of you",
    "career_money": "Career and money",
    "relationships": "Love and relationships",
    "energy_mindset": "Energy, mindset and habits",
    "remedies_manifestation": "Remedies and your manifestation practice",
    "months_ahead": "Month by month for the next 12 months",
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


def core_prompt(user: dict, nums: dict, chart_text: str) -> str:
    py, ch = nums["pythagorean"], nums["chaldean"]
    return f"""Write the complete Destiny OS core report for this person.

Name (as given at birth): {user['name']}
Date of birth: {user['dob']}  ·  Birth time: {user['birth_time'] or 'not known'}  ·  Birth city: {user['city']}
Pythagorean: Life Path {py['lifePath']}, Birth number {py['birthNumber']}, Expression {py['expressionCompound']}/{py['expression']}, Soul Urge {py['soulUrge']}, Personality {py['personality']}, Personal Year {py['personalYear']}
Chaldean: Expression {ch['expressionCompound']}/{ch['expression']}, Soul Urge {ch['soulUrge']}, Personality {ch['personality']}
{chart_text}
Manifestation goal they've shared: {user.get('manifest_goal') or 'none yet'}
Today: {date.today().isoformat()}

Write warmly and specifically to THIS person, second person ("you"). Cross-check the two numerology systems and say where they agree or differ. Use the chart facts given; never invent planetary positions.
Reply with only JSON: {{"headline": string (under 12 words), "sections": {{
 "overview": string (90-120 words),
 "life_path": string (110-140 words),
 "name_number": string (100-130 words, compare Pythagorean and Chaldean),
 "chart_basics": string (100-130 words: Moon sign, nakshatra, lagna if known),
 "year_ahead": string (80-110 words on Personal Year {py['personalYear']}),
 "soul_personality": string (130-160 words),
 "dasha_now": string (150-190 words: Mahadasha and Antardasha themes and timing),
 "career_money": string (150-190 words, practical; no specific investments),
 "relationships": string (130-160 words),
 "energy_mindset": string (130-160 words, evidence-based habits: sleep, focus, stress),
 "remedies_manifestation": string (150-190 words: traditional remedies framed as tradition, plus a 2-minute daily manifestation practice matched to their numbers and goal),
 "months_ahead": string (12 short lines, one per month starting next month, "Month YYYY: theme, one action")
}}}}"""


def shape_core(data: dict, subscribed: bool) -> dict:
    out = {"headline": data.get("headline", ""), "numbers": data.get("numbers"),
           "chart_brief": data.get("chart_brief"), "created_at": data.get("created_at"), "sections": []}
    sec = data.get("sections", {})
    for sid in FREE_SECTIONS + LOCKED_SECTIONS:
        body = str(sec.get(sid, "")).strip()
        locked = sid in LOCKED_SECTIONS and not subscribed
        if locked:
            first = body.split(". ")[0][:120].rstrip(".,; ")
            out["sections"].append({"id": sid, "title": SECTION_TITLES[sid], "locked": True,
                                    "teaser": (first + "…") if first else ""})
        else:
            out["sections"].append({"id": sid, "title": SECTION_TITLES[sid], "locked": False, "body": body})
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


def get_core(user_id: int) -> dict | None:
    r = db.one("SELECT data FROM reports WHERE user_id=? AND kind='core' ORDER BY created_at DESC LIMIT 1", user_id)
    return json.loads(r["data"]) if r else None


def require_kind(kind: str):
    if kind not in ("compatibility", "annual"):
        raise HTTPException(404, "Unknown report.")
