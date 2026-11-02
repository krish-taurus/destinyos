"""SQLite storage for Destiny OS accounts, reports and billing.

One file on the droplet (DESTINY_DB, default /var/lib/destinyos/destinyos.db).
SQLite is plenty for one server; move to Postgres before running more than one API instance.
"""
from __future__ import annotations
import json, os, sqlite3, threading, time
from contextlib import contextmanager

DB_PATH = os.getenv("DESTINY_DB", "/var/lib/destinyos/destinyos.db")
_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id            INTEGER PRIMARY KEY,
  phone         TEXT UNIQUE NOT NULL,          -- E.164, e.g. +919876543210
  name          TEXT NOT NULL,
  dob           TEXT NOT NULL,                 -- YYYY-MM-DD
  birth_time    TEXT,                          -- HH:MM or NULL
  city          TEXT NOT NULL,
  source        TEXT,                          -- ?src= from the link they arrived on
  consent_at    INTEGER NOT NULL,              -- DPDP consent timestamp
  consent_text  TEXT NOT NULL,
  whatsapp_optin INTEGER NOT NULL DEFAULT 0,
  manifest_goal TEXT,
  free_questions_used INTEGER NOT NULL DEFAULT 0,
  created_at    INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS otps (
  phone      TEXT PRIMARY KEY,
  code_hash  TEXT NOT NULL,
  expires_at INTEGER NOT NULL,
  attempts   INTEGER NOT NULL DEFAULT 0,
  sent_at    INTEGER NOT NULL,
  sends_today INTEGER NOT NULL DEFAULT 1,
  day        TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
  token_hash TEXT PRIMARY KEY,
  user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  expires_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS reports (
  id         INTEGER PRIMARY KEY,
  user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  kind       TEXT NOT NULL,                    -- 'core' | 'compatibility' | 'annual'
  data       TEXT NOT NULL,                    -- JSON
  created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS subscriptions (
  id              INTEGER PRIMARY KEY,
  user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  provider_sub_id TEXT UNIQUE NOT NULL,        -- Razorpay subscription id
  status          TEXT NOT NULL,               -- created|authenticated|active|pending|halted|cancelled|completed
  current_end     INTEGER,                     -- paid-until (unix)
  updated_at      INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS purchases (
  id               INTEGER PRIMARY KEY,
  user_id          INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  item             TEXT NOT NULL,              -- consultation|compatibility|annual
  amount_paise     INTEGER NOT NULL,
  provider_order_id TEXT UNIQUE NOT NULL,
  provider_payment_id TEXT,
  status           TEXT NOT NULL,              -- created|paid|fulfilled
  details          TEXT,                       -- JSON (e.g. partner details)
  created_at       INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS usage (
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  day     TEXT NOT NULL,
  bucket  TEXT NOT NULL,
  n       INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (user_id, day, bucket)
);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY, user_id INTEGER, kind TEXT NOT NULL, data TEXT, at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS whatsapp_log (
  user_id INTEGER NOT NULL, day TEXT NOT NULL, status TEXT NOT NULL, detail TEXT,
  PRIMARY KEY (user_id, day)
);
"""


def _connect() -> sqlite3.Connection:
    d = os.path.dirname(DB_PATH)
    if d:
        os.makedirs(d, exist_ok=True)
    c = sqlite3.connect(DB_PATH, timeout=10, check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    c.execute("PRAGMA journal_mode = WAL")
    return c


_conn: sqlite3.Connection | None = None


def conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = _connect()
        _conn.executescript(SCHEMA)
    return _conn


def reset_for_tests(path: str):
    global _conn, DB_PATH
    DB_PATH = path
    _conn = None


@contextmanager
def tx():
    with _lock:
        c = conn()
        try:
            yield c
            c.commit()
        except Exception:
            c.rollback()
            raise


def one(sql: str, *args):
    r = conn().execute(sql, args).fetchone()
    return dict(r) if r else None


def all_(sql: str, *args):
    return [dict(r) for r in conn().execute(sql, args).fetchall()]


def now() -> int:
    return int(time.time())


def log_event(user_id: int | None, kind: str, data: dict | None = None):
    with tx() as c:
        c.execute("INSERT INTO events(user_id, kind, data, at) VALUES (?,?,?,?)",
                  (user_id, kind, json.dumps(data or {}), now()))
