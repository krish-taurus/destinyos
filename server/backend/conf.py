"""Service keys that can be set from the admin panel instead of editing /etc/destinyos.env.

A value saved in the panel is kept in the database and wins over the server file; clearing it falls back to the
file. Secrets are write-only: the panel is only ever told whether one is set and its last four characters.
The database file sits on the same disk, with the same protection, as the server file it replaces.
"""
from __future__ import annotations
import os, re, sys

import db

# key, label, group, secret, [(module, attribute)] to refresh in the running API
SPEC = [
    ("ANTHROPIC_API_KEY", "Anthropic API key", "AI: reports and chat", True, []),
    ("KIMI_API_KEY", "Kimi API key (optional stand-in)", "AI: reports and chat", True, [("main", "KIMI_API_KEY")]),
    ("MSG91_AUTH_KEY", "MSG91 auth key", "SMS sign-in codes", True, [("auth", "MSG91_AUTH_KEY")]),
    ("MSG91_TEMPLATE_ID", "MSG91 OTP template ID", "SMS sign-in codes", False, [("auth", "MSG91_TEMPLATE_ID")]),
    ("RAZORPAY_KEY_ID", "Razorpay key ID", "Payments", False, [("billing", "KEY_ID")]),
    ("RAZORPAY_KEY_SECRET", "Razorpay key secret", "Payments", True, [("billing", "KEY_SECRET")]),
    ("RAZORPAY_WEBHOOK_SECRET", "Razorpay webhook secret", "Payments", True, [("billing", "WEBHOOK_SECRET")]),
    ("RAZORPAY_PLAN_ID_CHAT", "Plan ID: HALIA Chat ₹499", "Payments", False, [("billing", "PLAN_ID_CHAT")]),
    ("RAZORPAY_PLAN_ID", "Plan ID: Destiny Plus ₹599", "Payments", False, [("billing", "PLAN_ID")]),
    ("RAZORPAY_PLAN_ID_VOICE", "Plan ID: Destiny Voice ₹999", "Payments", False, [("billing", "PLAN_ID_VOICE")]),
    ("WA_TOKEN", "WhatsApp Cloud API token", "WhatsApp", True, [("halia", "WA_TOKEN")]),
    ("WA_PHONE_ID", "WhatsApp phone number ID", "WhatsApp", False, [("halia", "WA_PHONE_ID")]),
    ("WA_NUMBER", "Public WhatsApp number (digits)", "WhatsApp", False, [("halia", "WA_NUMBER")]),
    ("WA_VERIFY_TOKEN", "Webhook verify token", "WhatsApp", True, [("halia", "WA_VERIFY_TOKEN")]),
    ("WA_APP_SECRET", "Meta app secret", "WhatsApp", True, [("halia", "WA_APP_SECRET")]),
    ("ELEVENLABS_API_KEY", "ElevenLabs API key", "Voice", True, [("voice", "API_KEY")]),
]
KEYS = {s[0]: s for s in SPEC}
_FILE = {k: os.getenv(k, "") for k in KEYS}        # what the server file gave us, before any panel value


def stored() -> dict:
    return {r["key"]: r["value"] for r in db.all_("SELECT key, value FROM app_settings") if r["key"] in KEYS}


def effective() -> dict:
    s = stored()
    return {k: s.get(k) or _FILE[k] for k in KEYS}


def load_env():
    """Put panel values into the environment. Called before the other modules read their settings."""
    for k, v in stored().items():
        if v:
            os.environ[k] = v


def apply():
    """Refresh the running API after a save, so no restart is needed."""
    eff = effective()
    for k, (_, _, _, _, targets) in KEYS.items():
        v = re.sub(r"\D", "", eff[k]) if k == "WA_NUMBER" else eff[k]
        if v:
            os.environ[k] = v
        else:
            os.environ.pop(k, None)
        for mod, attr in targets:
            if mod in sys.modules:
                setattr(sys.modules[mod], attr, v)
    if "auth" in sys.modules and "OTP_DEV_MODE" not in os.environ:
        sys.modules["auth"].OTP_DEV_MODE = not eff["MSG91_AUTH_KEY"]
    if "main" in sys.modules and eff["ANTHROPIC_API_KEY"]:
        from anthropic import Anthropic
        sys.modules["main"].client = Anthropic(api_key=eff["ANTHROPIC_API_KEY"])


def save(values: dict):
    """values: {KEY: text}. An empty string removes the panel value. Unknown keys are refused."""
    bad = [k for k in values if k not in KEYS]
    if bad:
        raise ValueError(f"Unknown setting: {bad[0]}")
    with db.tx() as c:
        for k, v in values.items():
            v = (v or "").strip()
            if len(v) > 500 or re.search(r"[\r\n\x00]", v):
                raise ValueError(f"{KEYS[k][1]}: that value doesn't look right.")
            if v:
                c.execute("INSERT INTO app_settings(key, value, updated_at) VALUES (?,?,?) "
                          "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at", (k, v, db.now()))
            else:
                c.execute("DELETE FROM app_settings WHERE key=?", (k,))
    apply()


def status() -> list[dict]:
    s = stored()
    out = []
    for k, label, group, secret, _ in SPEC:
        v = s.get(k) or _FILE[k]
        out.append({"key": k, "label": label, "group": group, "secret": secret, "set": bool(v),
                    "source": "panel" if s.get(k) else "server file" if _FILE[k] else None,
                    "shown": (("…" + v[-4:]) if secret and len(v) > 8 else "set" if secret else v) if v else ""})
    return out
