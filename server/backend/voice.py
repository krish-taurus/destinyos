"""ElevenLabs: the free voice briefing (text-to-speech in Dr. Krish's cloned voice) and the
₹999/month live voice chat (an ElevenLabs agent reached only through signed links).

/etc/destinyos.env:
    ELEVENLABS_API_KEY=...                 (Profile → API keys; needs Text to Speech + Agents access)
    ELEVENLABS_AGENT_ID=agent_8701m6ek1varfbcrfy378qtwk6gp
    ELEVENLABS_VOICE_EN=Kk69c9t0i5i4PqtTOnVl   krishenglish (cloned)
    ELEVENLABS_VOICE_HI=Lu5sT2uP5IFxIXICelyk   krish_2026 (professional clone, Hindi)
    VOICE_MINUTES=60                        included per calendar month on Destiny Voice
"""
from __future__ import annotations
import logging, os
from datetime import datetime, timezone, timedelta
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

import db
from auth import current_user
from billing import require_voice

log = logging.getLogger("destinyos.voice")
router = APIRouter(prefix="/api/voice")

API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
AGENT_ID = os.getenv("ELEVENLABS_AGENT_ID", "agent_8701m6ek1varfbcrfy378qtwk6gp")
VOICES = {"en": os.getenv("ELEVENLABS_VOICE_EN", "Kk69c9t0i5i4PqtTOnVl"),
          "hi": os.getenv("ELEVENLABS_VOICE_HI", "Lu5sT2uP5IFxIXICelyk")}
MINUTES = int(os.getenv("VOICE_MINUTES", "60"))
ASSUMED_SECONDS = 600            # a session counts as a full 10-minute call until ElevenLabs confirms its real length
RELEASES_PER_DAY = 3             # sessions that never connected can be given back, a few times a day
SIGNED_URL_TTL = 15 * 60         # ElevenLabs signed links stay usable for about 15 minutes
EL = "https://api.elevenlabs.io/v1"
AUDIO_DIR = Path(os.getenv("DESTINY_AUDIO_DIR", str(Path(os.getenv("DESTINY_DB", "/var/lib/destinyos/x.db")).parent / "audio")))
IST = timezone(timedelta(hours=5, minutes=30))
LANG_NAME = {"en": "English", "hi": "Hindi"}


def configured() -> bool:
    return bool(API_KEY)


def _el(method: str, path: str, **kw) -> httpx.Response:
    if not API_KEY:
        raise HTTPException(503, "Voice isn't switched on yet. Please try again soon.")
    r = httpx.request(method, EL + path, headers={"xi-api-key": API_KEY}, timeout=kw.pop("timeout", 60), **kw)
    if r.status_code >= 400:
        log.error("ElevenLabs %s %s -> %s %s", method, path, r.status_code, r.text[:300])
        raise HTTPException(502, "The voice service didn't respond. Please try again in a minute.")
    return r


# ── Voice briefing (text to speech) ──
def audio_path(user_id: int, report_id: int, lang: str) -> Path:
    return AUDIO_DIR / f"u{user_id}-r{report_id}-{lang}.mp3"


DISCLOSURE = {"en": "This briefing was created with Dr. Krish Bharggav's AI voice. It is guidance from tradition, not a prediction.",
              "hi": "यह ब्रीफ़िंग डॉ. कृष भार्गव की AI आवाज़ से बनाई गई है। यह परंपरा पर आधारित मार्गदर्शन है, भविष्यवाणी नहीं।"}


def with_disclosure(script: str, lang: str) -> str:
    """Always end the spoken briefing with a fixed AI disclosure, whatever the script writer produced."""
    return script.rstrip() + "\n\n" + DISCLOSURE.get(lang, DISCLOSURE["en"])


def synthesize(text: str, lang: str, dest: Path):
    r = _el("POST", f"/text-to-speech/{VOICES.get(lang, VOICES['en'])}",
            params={"output_format": "mp3_44100_128"}, timeout=120,
            json={"text": text, "model_id": "eleven_multilingual_v2", "language_code": lang,
                  "voice_settings": {"stability": 0.55, "similarity_boost": 0.85, "style": 0.15}})
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".part")
    tmp.write_bytes(r.content)
    tmp.replace(dest)


def delete_user_audio(user_id: int):
    if AUDIO_DIR.exists():
        for f in AUDIO_DIR.glob(f"u{user_id}-*.mp3"):
            f.unlink(missing_ok=True)


# ── Live voice chat metering ──
def month_key(ts: int | None = None) -> str:
    return datetime.fromtimestamp(ts or db.now(), IST).strftime("%Y-%m")


def seconds_used(user_id: int) -> int:
    r = db.one("SELECT COALESCE(SUM(seconds),0) AS s FROM voice_sessions WHERE user_id=? AND month=? AND released=0",
               user_id, month_key())
    return r["s"]


def minutes_status(user_id: int) -> dict:
    used = seconds_used(user_id)
    return {"included": MINUTES, "used_minutes": round(used / 60, 1),
            "left_minutes": max(0, round((MINUTES * 60 - used) / 60, 1))}


def reconcile(user_id: int):
    """Replace the assumed 10 minutes with the real call length for finished calls."""
    for s in db.all_("SELECT * FROM voice_sessions WHERE user_id=? AND final=0 AND conversation_id IS NOT NULL", user_id):
        try:
            d = _el("GET", f"/convai/conversations/{s['conversation_id']}", timeout=15).json()
        except HTTPException:
            continue
        if d.get("agent_id") and d["agent_id"] != AGENT_ID:
            continue                                         # not our agent: keep the assumed charge
        if d.get("status") in ("done", "failed"):
            secs = int((d.get("metadata") or {}).get("call_duration_secs") or 0)
            with db.tx() as c:
                c.execute("UPDATE voice_sessions SET seconds=?, final=1 WHERE id=?", (max(secs, 0), s["id"]))


@router.get("/status")
def status(u=Depends(current_user)):
    from billing import is_voice
    if is_voice(u["id"]) and configured():
        reconcile(u["id"])
        release_expired(u["id"])
    return {"voice": is_voice(u["id"]), "ready": configured(), **minutes_status(u["id"])}


@router.post("/session")
def session(u=Depends(require_voice)):
    from main import profile_text_for            # lazy: avoids a circular import
    release_expired(u["id"])
    with db.tx() as c:                      # check and reserve in one locked step: parallel requests can't overspend
        used = c.execute("SELECT COALESCE(SUM(seconds),0) FROM voice_sessions WHERE user_id=? AND month=? AND released=0",
                         (u["id"], month_key())).fetchone()[0]
        if used + 60 > MINUTES * 60:
            raise HTTPException(402, f"You've used your {MINUTES} voice minutes this month. They renew on the 1st.")
        starting = c.execute("SELECT COUNT(*) FROM voice_sessions WHERE user_id=? AND final=0 AND released=0 "
                             "AND conversation_id IS NULL AND issued_at>?", (u["id"], db.now() - 120)).fetchone()[0]
        if starting >= 1:
            raise HTTPException(429, "A call is already starting. Wait a moment and try again.")
        sid = c.execute("INSERT INTO voice_sessions(user_id, issued_at, month, seconds) VALUES (?,?,?,?)",
                        (u["id"], db.now(), month_key(), ASSUMED_SECONDS)).lastrowid
    try:
        signed = _el("GET", "/convai/conversation/get-signed-url", params={"agent_id": AGENT_ID}, timeout=15).json()["signed_url"]
    except Exception:
        with db.tx() as c:
            c.execute("DELETE FROM voice_sessions WHERE id=?", (sid,))
        raise
    lang = u.get("language") or "en"
    return {"session_id": sid, "signed_url": signed,
            "dynamic_variables": {"user_name": u["name"].split()[0], "language_name": LANG_NAME.get(lang, "English"),
                                  "profile": profile_text_for(u)[:3500], "today": datetime.now(IST).strftime("%A, %d %B %Y")},
            "overrides": {"agent": {"language": lang}},
            **minutes_status(u["id"])}


class StartedIn(BaseModel):
    session_id: int
    conversation_id: str = Field(min_length=4, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")


@router.post("/started")
def started(body: StartedIn, u=Depends(current_user)):
    with db.tx() as c:
        cur = c.execute("UPDATE voice_sessions SET conversation_id=? WHERE id=? AND user_id=? AND conversation_id IS NULL",
                        (body.conversation_id, body.session_id, u["id"]))
    if cur.rowcount == 0:
        raise HTTPException(404, "Unknown call.")
    return {"ok": True}


class EndedIn(BaseModel):
    session_id: int


@router.post("/ended")
def ended(body: EndedIn, u=Depends(current_user)):
    reconcile(u["id"])
    return minutes_status(u["id"])


def _unclaimed_call_between(start: int, end: int) -> bool:
    """True if ElevenLabs has any call on our agent that started in [start, end] and no session has claimed.
    Conservative: if we can't check, assume there was one."""
    try:
        d = _el("GET", "/convai/conversations", params={"agent_id": AGENT_ID, "call_start_after_unix": start - 5,
                                                         "call_start_before_unix": end + 5, "page_size": 100}, timeout=15).json()
    except HTTPException:
        return True
    ids = [c.get("conversation_id") for c in d.get("conversations", [])
           if c.get("conversation_id") and start - 5 <= int(c.get("start_time_unix_secs") or start) <= end + 5]
    if not ids:
        return False
    marks = ",".join("?" * len(ids))
    claimed = {r["conversation_id"] for r in db.all_(f"SELECT conversation_id FROM voice_sessions WHERE conversation_id IN ({marks})", *ids)}
    return any(i not in claimed for i in ids)


@router.post("/release")
def release(body: EndedIn, u=Depends(current_user)):
    """Give back a session that never connected (microphone blocked, network failed). Only once its signed
    link has expired, and only if no unclaimed call started on the agent while the link was valid,
    so a link can't be 'released' and still used."""
    today_start = int(datetime.now(IST).replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
    s = db.one("SELECT * FROM voice_sessions WHERE id=? AND user_id=? AND conversation_id IS NULL AND final=0",
               body.session_id, u["id"])
    if not s:
        return {"released": False, **minutes_status(u["id"])}
    if db.now() < s["issued_at"] + SIGNED_URL_TTL:
        return {"released": False, "pending": True, **minutes_status(u["id"])}
    used = db.one("SELECT COUNT(*) AS n FROM voice_sessions WHERE user_id=? AND released=1 AND issued_at>=?",
                  u["id"], today_start)["n"]
    if used >= RELEASES_PER_DAY or _unclaimed_call_between(s["issued_at"], s["issued_at"] + SIGNED_URL_TTL):
        return {"released": False, **minutes_status(u["id"])}
    with db.tx() as c:
        c.execute("UPDATE voice_sessions SET released=1, seconds=0, final=1 WHERE id=? AND final=0", (s["id"],))
    return {"released": True, **minutes_status(u["id"])}


def release_expired(user_id: int):
    """Automatically give back this user's never-connected sessions whose links have expired."""
    for s in db.all_("SELECT id FROM voice_sessions WHERE user_id=? AND conversation_id IS NULL AND final=0 AND released=0 "
                     "AND issued_at<?", user_id, db.now() - SIGNED_URL_TTL):
        try:
            release(EndedIn(session_id=s["id"]), {"id": user_id})
        except Exception:
            pass
