"""Send each opted-in person one HALIA question a day on WhatsApp; their reply is saved to their profile.

Run daily at 19:00 IST by the destinyos-halia-daily.timer systemd unit:
    /var/www/destinyos/venv/bin/python halia_daily.py            # send
    /var/www/destinyos/venv/bin/python halia_daily.py --dry-run  # print, send nothing

Who gets one: accepted HALIA consent, switched daily questions on, and WhatsApp messages on. Never a
sensitive question, never more than one a day, and a skipped question rests for a week (halia_engine).
Replies arrive at POST /api/whatsapp/webhook (halia.py). Reply STOP pauses the questions.

Business-initiated messages need an approved template. In /etc/destinyos.env:
    WA_TEMPLATE_QUESTION=halia_question     Utility template, body:
      Hi {{1}}, today's quick question from Destiny OS: {{2}} Reply with the number: {{3}}. Reply SKIP to skip or STOP to pause these.
Without WA_TOKEN / WA_PHONE_ID the script runs as a dry run.
"""
from __future__ import annotations
import argparse, logging, os, sys
from datetime import date

import httpx

import db, conf
conf.load_env()          # keys saved in the admin panel
import halia
import halia_engine as eng
from daily_whatsapp import clean

log = logging.getLogger("destinyos.halia_daily")
WA_TOKEN = os.getenv("WA_TOKEN", "")
WA_PHONE_ID = os.getenv("WA_PHONE_ID", "")
WA_TEMPLATE = os.getenv("WA_TEMPLATE_QUESTION", "halia_question")
WA_LANG = os.getenv("WA_TEMPLATE_LANG", "en")


def params(u: dict, q: dict) -> list[str]:
    opts = "  ".join(f"{i}) {o['label']}" for i, o in enumerate(q["options"], 1))
    return [clean(u["name"].split()[0], 40), clean(q["text"], 200), clean(opts, 500)]


def send(phone: str, p: list[str]):
    r = httpx.post(f"https://graph.facebook.com/v21.0/{WA_PHONE_ID}/messages",
                   headers={"Authorization": f"Bearer {WA_TOKEN}"}, timeout=20,
                   json={"messaging_product": "whatsapp", "to": phone.lstrip("+"), "type": "template",
                         "template": {"name": WA_TEMPLATE, "language": {"code": WA_LANG},
                                      "components": [{"type": "body", "parameters": [{"type": "text", "text": x} for x in p]}]}})
    if r.status_code >= 400:
        raise RuntimeError(f"WhatsApp {r.status_code}: {r.text[:300]}")


def run(dry: bool) -> dict:
    today = date.today()
    stats = {"eligible": 0, "sent": 0, "nothing_to_ask": 0, "failed": 0}
    for u in db.all_("SELECT u.* FROM users u JOIN halia_settings s ON s.user_id=u.id WHERE s.daily_optin=1 AND u.whatsapp_optin=1"):
        stats["eligible"] += 1
        q = eng.next_question(halia.facts(u["id"]), halia.qlog(u["id"]), today, unprompted=True)
        if not q:
            stats["nothing_to_ask"] += 1
            continue
        p = params(u, q)
        if dry:
            print(u["phone"][:-4] + "****", "|", " | ".join(p))
            continue
        try:
            send(u["phone"], p)
        except Exception:                                # one failure never stops the rest
            log.exception("daily question failed for user %s", u["id"])
            stats["failed"] += 1
            continue
        with db.tx() as c:
            halia._log_q(c, u["id"], q["id"], "whatsapp", "asked")
        stats["sent"] += 1
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
