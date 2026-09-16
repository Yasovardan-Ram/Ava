from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path

try:
    from flask import has_request_context, session
except Exception:  # pragma: no cover
    has_request_context = lambda: False
    session = None

import os
DATA_DIR = Path(os.environ.get("AVA_RUNTIME_DIR", "/tmp/ava_runtime" if os.environ.get("VERCEL") else str(Path(__file__).resolve().parent.parent / "data")))
DB_FILE = Path(os.environ.get("AVA_DB_FILE", str(DATA_DIR / "ava_runtime.sqlite3")))


def session_id() -> str:
    from app.jobs import current_session_override
    override = current_session_override()
    if override:
        return override
    """Return a stable per-browser building namespace."""
    if has_request_context():
        sid = session.get("ava_session_id")
        if not sid:
            sid = uuid.uuid4().hex
            session["ava_session_id"] = sid
        return sid
    return "local-default"


def _connect():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_FILE, timeout=10.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=10000")
    conn.execute("CREATE TABLE IF NOT EXISTS kv (session_id TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL, updated_at TEXT DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(session_id,key))")
    conn.execute("CREATE TABLE IF NOT EXISTS history (session_id TEXT NOT NULL, id INTEGER PRIMARY KEY AUTOINCREMENT, value TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP)")
    return conn


def get_json(key: str):
    sid = session_id()
    with _connect() as conn:
        row = conn.execute("SELECT value FROM kv WHERE session_id=? AND key=?", (sid, key)).fetchone()
    if not row:
        return None
    return json.loads(row[0])


def put_json(key: str, value) -> None:
    sid = session_id()
    payload = json.dumps(value, separators=(",", ":"))
    with _connect() as conn:
        conn.execute("INSERT INTO kv(session_id,key,value,updated_at) VALUES(?,?,?,CURRENT_TIMESTAMP) ON CONFLICT(session_id,key) DO UPDATE SET value=excluded.value, updated_at=CURRENT_TIMESTAMP", (sid, key, payload))


def delete_key(key: str) -> None:
    sid = session_id()
    with _connect() as conn:
        conn.execute("DELETE FROM kv WHERE session_id=? AND key=?", (sid, key))


def append_history(value, limit: int = 1000) -> None:
    sid = session_id()
    payload = json.dumps(value, separators=(",", ":"))
    with _connect() as conn:
        conn.execute("INSERT INTO history(session_id,value) VALUES(?,?)", (sid, payload))
        conn.execute("DELETE FROM history WHERE session_id=? AND id NOT IN (SELECT id FROM history WHERE session_id=? ORDER BY id DESC LIMIT ?)", (sid, sid, limit))


def load_history():
    sid = session_id()
    with _connect() as conn:
        rows = conn.execute("SELECT value FROM history WHERE session_id=? ORDER BY id ASC", (sid,)).fetchall()
    return [json.loads(row[0]) for row in rows]


def clear_history() -> None:
    sid = session_id()
    with _connect() as conn:
        conn.execute("DELETE FROM history WHERE session_id=?", (sid,))
