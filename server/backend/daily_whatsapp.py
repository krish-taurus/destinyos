"""Send each opted-in Destiny Plus subscriber their morning guidance and manifestation practice on WhatsApp.

Run daily at 7:00 IST by the destinyos-daily.timer systemd unit:
    /var/www/destinyos/venv/bin/python daily_whatsapp.py            # send
    /var/www/destinyos/venv/bin/python daily_whatsapp.py --dry-run  # print, send nothing

WhatsApp Cloud API (Meta) setup, in /etc/destinyos.env:
    WA_TOKEN=...           permanent system-user token
    WA_PHONE_ID=...        phone number ID of the Destiny OS WhatsApp number
    WA_TEMPLATE=destiny_daily   approved Utility/Marketing template, language en, body:
      Good morning {{1}} ☀️ Today is your Personal Day {{2}}: {{3}}. Wear {{4}}. Today's practice: {{5}} Open your Destiny OS panel to ask anything: destinyos.in/app
Business-initiated messages need an approved template; free-form text only works inside a 24-hour reply window.
Without WA_TOKEN the script runs as a dry run.
"""
from __future__ import annotations
import argparse, logging, os, re, sys
from datetime import date

import httpx

import db, numerology
from billing import is_subscriber

log = logging.getLogger("destinyos.daily")
WA_TOKEN = os.getenv("WA_TOKEN", "")
WA_PHONE_ID = os.getenv("WA_PHONE_ID", "")
WA_TEMPLATE = os.getenv("WA_TEMPLATE", "destiny_daily")
WA_LANG = os.getenv("WA_TEMPLATE_LANG", "en")


def clean(t: str, n: int) -> str:
    """Template parameters can't contain newlines, tabs or 4+ spaces in a row."""
    t = re.sub(r"\s+", " ", str(t or "")).strip()
    return t[:n].rstrip()


def compose(u: dict) -> list[str]:
    from main import ask_claude, parse_json, profile_text_for, FAST_MODEL, GUARDRAILS, LANG_RULE   # lazy: needs API keys
    n = numerology.calc(u["name"], u["dob"])
    pd = n["personalDay"]
    prompt = f"""Write today's WhatsApp morning message parts for this subscriber.
{profile_text_for(u)}
Reply with only JSON: {{"theme": string (Personal Day {pd} theme in 3-6 words), "wear": string (1-2 colours, e.g. "light green"),
"practice": string (a 2-minute manifestation practice for today, matched to Personal Day {pd} and their goal if set,
with the exact words to write or say; under 220 characters)}}
{LANG_RULE.get(u.get('language') or 'en', LANG_RULE['en'])} Keep the JSON keys in English."""
    out = parse_json(ask_claude(f"You write short WhatsApp messages for Destiny OS.\n{GUARDRAILS}",
                                [{"role": "user", "content": prompt}], model=FAST_MODEL, max_tokens=400))
    return [clean(u["name"].split()[0], 40), str(pd), clean(out.get("theme"), 60),
            clean(out.get("wear"), 40), clean(out.get("practice"), 400)]


def send(phone: str, params: list[str]):
    r = httpx.post(f"https://graph.facebook.com/v21.0/{WA_PHONE_ID}/messages",
                   headers={"Authorization": f"Bearer {WA_TOKEN}"}, timeout=20,
                   json={"messaging_product": "whatsapp", "to": phone.lstrip("+"), "type": "template",
                         "template": {"name": WA_TEMPLATE, "language": {"code": WA_LANG},
                                      "components": [{"type": "body", "parameters":
                                                      [{"type": "text", "text": p} for p in params]}]}})
    if r.status_code >= 400:
        raise RuntimeError(f"WhatsApp {r.status_code}: {r.text[:300]}")


def run(dry: bool) -> dict:
    today = date.today().isoformat()
    stats = {"eligible": 0, "sent": 0, "skipped": 0, "failed": 0}
    for u in db.all_("SELECT * FROM users WHERE whatsapp_optin=1"):
        if not is_subscriber(u["id"]):
            continue
        stats["eligible"] += 1
        if db.one("SELECT 1 FROM whatsapp_log WHERE user_id=? AND day=? AND status='sent'", u["id"], today):
            stats["skipped"] += 1
            continue
        try:
            params = compose(u)
            if dry:
                print(u["phone"][:-4] + "****", "|", " | ".join(params))
                continue
            send(u["phone"], params)
            status, detail = "sent", None
            stats["sent"] += 1
        except Exception as e:                       # one failure never stops the rest
            log.exception("daily message failed for user %s", u["id"])
            status, detail = "failed", str(e)[:300]
            stats["failed"] += 1
        with db.tx() as c:
            c.execute("INSERT OR REPLACE INTO whatsapp_log(user_id, day, status, detail) VALUES (?,?,?,?)",
                      (u["id"], today, status, detail))
    return stats


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    dry = a.dry_run or not (WA_TOKEN and WA_PHONE_ID)
    if dry and not a.dry_run:
        print("WA_TOKEN / WA_PHONE_ID not set: dry run, nothing sent.")
    print(run(dry))
    sys.exit(0)
