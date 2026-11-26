"""HALIA Match: opt-in matchmaking ranked by the HALIA alignment engine (the 'couple' domain).

How it works
  - Adults only, and only people who turned HALIA on and wrote a match profile are ever shown.
  - The deck holds people whose preferences and yours fit both ways, best alignment first.
  - Swipe right = like, left = pass, up = a strong yes (they see you first). Two likes make a match.
  - Before a match you see a first name, age, city, a short note and area-by-area alignment. Individual
    answers are shown only after a match, to both sides. Phone numbers are never shown.
  - Alignment is how closely two people's stated answers agree. It is not a prediction.
"""
from __future__ import annotations
import re
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import db
import halia
import halia_engine as eng
from auth import current_user

router = APIRouter(prefix="/api/match")
LIKES_PER_DAY, SUPERS_PER_DAY, MESSAGES_PER_HOUR, DECK = 60, 3, 60, 20
CONSENT_TEXT = ("Show me to other adults on HALIA Match. They will see my first name, age, city, my short note and how "
                "closely our answers agree, area by area. My individual answers are shown only to people I match with, "
                "and my phone number is never shown. I can hide or delete my profile at any time.")
GENDERS, SEEKING, INTENTS = ("woman", "man", "other"), ("women", "men", "everyone"), ("marriage", "long_term", "friendship")
INTENT_LABEL = {"marriage": "Looking to marry", "long_term": "Long-term relationship", "friendship": "Friendship first"}


def profile(user_id: int) -> dict | None:
    return db.one("SELECT * FROM match_profiles WHERE user_id=?", user_id)


def member(u=Depends(current_user)) -> dict:
    if halia._age(u["dob"]) < 18:
        raise HTTPException(403, "HALIA Match is for adults aged 18 and over.")
    if not halia.settings(u["id"]):
        raise HTTPException(403, "Turn on HALIA first.")
    p = profile(u["id"])
    if not p:
        raise HTTPException(409, "Create your match profile first.")
    return {**u, "mp": p}


def _wants(seeking: str, gender: str) -> bool:
    return seeking == "everyone" or (seeking == "women" and gender == "woman") or (seeking == "men" and gender == "man")


def _fits(me: dict, my_age: int, them: dict, their_age: int) -> bool:
    return (_wants(me["seeking"], them["gender"]) and _wants(them["seeking"], me["gender"])
            and me["age_min"] <= their_age <= me["age_max"] and them["age_min"] <= my_age <= them["age_max"])


def _blocked(a: int, b: int) -> bool:
    return bool(db.one("SELECT 1 FROM match_blocks WHERE (user_id=? AND target_id=?) OR (user_id=? AND target_id=?)", a, b, b, a))


def _card(p: dict, dob: str, al: dict, keen: bool = False) -> dict:
    out = {"id": p["user_id"], "name": p["display_name"], "age": halia._age(dob), "city": p["city"],
           "intent": INTENT_LABEL[p["intent"]], "bio": p["bio"], "keen": keen, "enough": al["enough"], "note": eng.NOTE}
    if al["enough"]:
        out.update(score=al["score"], areas=[{"name": a["name"], "score": a["score"]} for a in al["areas"] if a["score"] is not None])
    return out


# ── Profile ──
class ProfileIn(BaseModel):
    display_name: str = Field(min_length=2, max_length=30)
    gender: str
    seeking: str
    age_min: int = Field(ge=18, le=80)
    age_max: int = Field(ge=18, le=80)
    city: str = Field(min_length=2, max_length=60)
    intent: str
    bio: str = Field(default="", max_length=200)
    consent: bool = False
    active: bool = True


@router.get("/profile")
def profile_get(u=Depends(current_user)):
    p = profile(u["id"])
    cov = eng.coverage("couple", halia.facts(u["id"])) if halia.settings(u["id"]) else {"answered": 0, "of": len(eng.domain_fields("couple"))}
    return {"adult": halia._age(u["dob"]) >= 18, "halia_on": bool(halia.settings(u["id"])), "halia_consent_text": halia.CONSENT_TEXT,
            "consent_text": CONSENT_TEXT, "first_name": u["name"].split()[0], "city": u["city"], "age": halia._age(u["dob"]),
            "profile": p and {k: p[k] for k in ("display_name", "gender", "seeking", "age_min", "age_max", "city", "intent", "bio", "active")},
            "answers": cov, "limits": {"likes": LIKES_PER_DAY, "strong": SUPERS_PER_DAY}}


@router.put("/profile")
def profile_put(body: ProfileIn, u=Depends(current_user)):
    if halia._age(u["dob"]) < 18:
        raise HTTPException(403, "HALIA Match is for adults aged 18 and over.")
    if not halia.settings(u["id"]):
        raise HTTPException(403, "Turn on HALIA first.")
    if body.gender not in GENDERS or body.seeking not in SEEKING or body.intent not in INTENTS:
        raise HTTPException(422, "Choose from the listed options.")
    if body.age_min > body.age_max:
        raise HTTPException(422, "The youngest age must be below the oldest.")
    had = profile(u["id"])
    if not had and not body.consent:
        raise HTTPException(422, "Tick the box to be shown to other people.")
    name = re.sub(r"[^\w .'-]", "", body.display_name).strip()[:30]
    bio = re.sub(r"\s+", " ", body.bio).strip()
    if len(name) < 2:
        raise HTTPException(422, "Enter the first name to show.")
    if re.search(r"\d{6,}|@|https?://|www\.", bio):
        raise HTTPException(422, "Leave phone numbers, links and handles out of your note. You can share them after you match.")
    with db.tx() as c:
        c.execute("INSERT INTO match_profiles(user_id, display_name, gender, seeking, age_min, age_max, city, intent, bio, active, "
                  "consent_text, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET "
                  "display_name=excluded.display_name, gender=excluded.gender, seeking=excluded.seeking, age_min=excluded.age_min, "
                  "age_max=excluded.age_max, city=excluded.city, intent=excluded.intent, bio=excluded.bio, active=excluded.active, "
                  "updated_at=excluded.updated_at",
                  (u["id"], name, body.gender, body.seeking, body.age_min, body.age_max, body.city.strip(), body.intent, bio,
                   int(body.active), CONSENT_TEXT, db.now(), db.now()))
    if not had:
        db.log_event(u["id"], "match_join")
    return {"ok": True}


def erase(user_id: int):
    with db.tx() as c:
        c.execute("DELETE FROM matches WHERE user_a=? OR user_b=?", (user_id, user_id))
        c.execute("DELETE FROM match_swipes WHERE user_id=? OR target_id=?", (user_id, user_id))
        c.execute("DELETE FROM match_profiles WHERE user_id=?", (user_id,))


@router.delete("/profile")
def profile_delete(u=Depends(current_user)):
    """Leaving removes your profile, your swipes, your matches and their messages."""
    erase(u["id"])
    db.log_event(u["id"], "match_leave")
    return {"ok": True}


# ── Deck ──
def _left_today(user_id: int) -> dict:
    rows = db.all_("SELECT action, COUNT(*) n FROM match_swipes WHERE user_id=? AND day=? GROUP BY action", user_id, date.today().isoformat())
    n = {r["action"]: r["n"] for r in rows}
    return {"likes": max(0, LIKES_PER_DAY - n.get("like", 0) - n.get("super", 0)), "strong": max(0, SUPERS_PER_DAY - n.get("super", 0))}


@router.get("/deck")
def deck(u=Depends(member)):
    me, my_age, mine = u["mp"], halia._age(u["dob"]), halia.values(u["id"])
    if not me["active"]:
        return {"cards": [], "hidden": True, "left": _left_today(u["id"])}
    rows = db.all_(
        "SELECT p.*, x.dob FROM match_profiles p JOIN users x ON x.id=p.user_id JOIN halia_settings h ON h.user_id=p.user_id "
        "WHERE p.active=1 AND p.user_id!=? AND p.user_id NOT IN (SELECT target_id FROM match_swipes WHERE user_id=?) "
        "AND p.user_id NOT IN (SELECT target_id FROM match_blocks WHERE user_id=?) "
        "AND p.user_id NOT IN (SELECT user_id FROM match_blocks WHERE target_id=?) LIMIT 500", u["id"], u["id"], u["id"], u["id"])
    keen = {r["user_id"] for r in db.all_("SELECT user_id FROM match_swipes WHERE target_id=? AND action='super'", u["id"])}
    cards = []
    for p in rows:
        if halia._age(p["dob"]) < 18 or not _fits(me, my_age, p, halia._age(p["dob"])):
            continue
        al = eng.align("couple", mine, halia.values(p["user_id"]))
        cards.append(_card(p, p["dob"], al, p["user_id"] in keen))
    cards.sort(key=lambda c: (not c["keen"], not c["enough"], -(c.get("score") or 0), c["id"]))
    cov = eng.coverage("couple", halia.facts(u["id"]))
    return {"cards": cards[:DECK], "hidden": False, "left": _left_today(u["id"]), "answers": cov}


class SwipeIn(BaseModel):
    target_id: int
    action: str


@router.post("/swipe")
def swipe(body: SwipeIn, u=Depends(member)):
    if body.action not in ("like", "pass", "super"):
        raise HTTPException(422, "Unknown action.")
    t = db.one("SELECT p.*, x.dob FROM match_profiles p JOIN users x ON x.id=p.user_id WHERE p.user_id=? AND p.active=1", body.target_id)
    if not t or body.target_id == u["id"] or _blocked(u["id"], body.target_id) or not u["mp"]["active"] \
            or not _fits(u["mp"], halia._age(u["dob"]), t, halia._age(t["dob"])):
        raise HTTPException(404, "That profile is no longer available.")
    if db.one("SELECT 1 FROM match_swipes WHERE user_id=? AND target_id=?", u["id"], body.target_id):
        raise HTTPException(409, "You have already answered this profile.")
    left = _left_today(u["id"])
    if body.action == "super" and not left["strong"]:
        raise HTTPException(429, f"You have used today's {SUPERS_PER_DAY} strong yeses. Swipe right to like instead.")
    if body.action != "pass" and not left["likes"]:
        raise HTTPException(429, "That's all your likes for today. Come back tomorrow.")
    mid = None
    with db.tx() as c:
        c.execute("INSERT INTO match_swipes(user_id, target_id, action, day, at) VALUES (?,?,?,?,?)",
                  (u["id"], body.target_id, body.action, date.today().isoformat(), db.now()))
        back = c.execute("SELECT action FROM match_swipes WHERE user_id=? AND target_id=?", (body.target_id, u["id"])).fetchone()
        if body.action != "pass" and back and back["action"] in ("like", "super"):
            a, b = sorted((u["id"], body.target_id))
            c.execute("INSERT OR IGNORE INTO matches(user_a, user_b, at) VALUES (?,?,?)", (a, b, db.now()))
            mid = c.execute("SELECT id FROM matches WHERE user_a=? AND user_b=?", (a, b)).fetchone()["id"]
    if mid:
        db.log_event(u["id"], "match_made", {"match": mid})
    return {"ok": True, "matched": bool(mid), "match_id": mid, "name": t["display_name"] if mid else None, "left": _left_today(u["id"])}


# ── Matches and messages ──
def _my_match(match_id: int, user_id: int) -> tuple[dict, int]:
    m = db.one("SELECT * FROM matches WHERE id=? AND (user_a=? OR user_b=?)", match_id, user_id, user_id)
    if not m:
        raise HTTPException(404, "That match no longer exists.")
    return m, (m["user_b"] if m["user_a"] == user_id else m["user_a"])


@router.get("/matches")
def matches(u=Depends(member)):
    out = []
    for m in db.all_("SELECT * FROM matches WHERE user_a=? OR user_b=? ORDER BY at DESC", u["id"], u["id"]):
        other = m["user_b"] if m["user_a"] == u["id"] else m["user_a"]
        p = db.one("SELECT p.*, x.dob FROM match_profiles p JOIN users x ON x.id=p.user_id WHERE p.user_id=?", other)
        if not p:
            continue
        last = db.one("SELECT body, sender_id, at FROM match_messages WHERE match_id=? ORDER BY id DESC LIMIT 1", m["id"])
        al = eng.align("couple", halia.values(u["id"]), halia.values(other))
        out.append({"match_id": m["id"], "name": p["display_name"], "age": halia._age(p["dob"]), "city": p["city"],
                    "score": al.get("score"), "at": m["at"],
                    "last": last and {"body": last["body"][:80], "mine": last["sender_id"] == u["id"], "at": last["at"]}})
    return {"matches": out}


@router.get("/matches/{match_id}")
def match_get(match_id: int, after: int = 0, u=Depends(member)):
    m, other = _my_match(match_id, u["id"])
    p = db.one("SELECT p.*, x.dob FROM match_profiles p JOIN users x ON x.id=p.user_id WHERE p.user_id=?", other)
    if not p:
        raise HTTPException(404, "That match no longer exists.")
    msgs = db.all_("SELECT id, sender_id, body, at FROM match_messages WHERE match_id=? AND id>? ORDER BY id LIMIT 200", match_id, after)
    al = eng.align("couple", halia.values(u["id"]), halia.values(other))
    return {"match_id": match_id, "person": _card(p, p["dob"], al), "talk_about": al.get("talk_about", []),
            "messages": [{"id": x["id"], "mine": x["sender_id"] == u["id"], "body": x["body"], "at": x["at"]} for x in msgs]}


class MessageIn(BaseModel):
    body: str = Field(min_length=1, max_length=500)


@router.post("/matches/{match_id}/messages")
def message(match_id: int, body: MessageIn, u=Depends(member)):
    _, other = _my_match(match_id, u["id"])
    if _blocked(u["id"], other):
        raise HTTPException(404, "That match no longer exists.")
    text = body.body.strip()
    if not text:
        raise HTTPException(422, "Write a message first.")
    if db.one("SELECT COUNT(*) n FROM match_messages WHERE sender_id=? AND at>?", u["id"], db.now() - 3600)["n"] >= MESSAGES_PER_HOUR:
        raise HTTPException(429, "You're sending messages very quickly. Try again in a little while.")
    with db.tx() as c:
        cur = c.execute("INSERT INTO match_messages(match_id, sender_id, body, at) VALUES (?,?,?,?)", (match_id, u["id"], text, db.now()))
    return {"id": cur.lastrowid, "mine": True, "body": text, "at": db.now()}


@router.delete("/matches/{match_id}")
def unmatch(match_id: int, u=Depends(member)):
    _, other = _my_match(match_id, u["id"])
    with db.tx() as c:
        c.execute("DELETE FROM matches WHERE id=?", (match_id,))
        c.execute("UPDATE match_swipes SET action='pass' WHERE user_id=? AND target_id=?", (u["id"], other))
    return {"ok": True}


class ReportIn(BaseModel):
    target_id: int
    reason: str = Field(default="", max_length=300)


@router.post("/report")
def report(body: ReportIn, u=Depends(member)):
    """Block someone and tell the team why. They disappear from your deck and any match with them ends."""
    if body.target_id == u["id"] or not db.one("SELECT 1 FROM users WHERE id=?", body.target_id):
        raise HTTPException(404, "That profile is no longer available.")
    a, b = sorted((u["id"], body.target_id))
    with db.tx() as c:
        c.execute("INSERT OR IGNORE INTO match_blocks(user_id, target_id, reason, at) VALUES (?,?,?,?)",
                  (u["id"], body.target_id, body.reason.strip()[:300], db.now()))
        c.execute("DELETE FROM matches WHERE user_a=? AND user_b=?", (a, b))
    db.log_event(u["id"], "match_report", {"target": body.target_id})
    return {"ok": True}
