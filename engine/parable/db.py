import sqlite3
import threading
from pathlib import Path

from parable.config import get_settings

DB_LOCK = threading.RLock()
_connection: sqlite3.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS sellers (
    id TEXT PRIMARY KEY,
    paypal_payer_id TEXT UNIQUE,
    name TEXT,
    email TEXT,
    verified INTEGER DEFAULT 0,
    created_at INTEGER
);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    seller_id TEXT,
    listing_id TEXT,
    purchase_id TEXT,
    purpose TEXT,
    name TEXT,
    rules_json TEXT,
    fingerprint TEXT,
    status TEXT,
    cause TEXT,
    cash_usd INTEGER,
    eth_wei INTEGER,
    start_cash_usd INTEGER,
    peak_equity_usd INTEGER,
    final_equity_usd INTEGER,
    started_at INTEGER,
    expires_at INTEGER,
    ended_at INTEGER,
    trades INTEGER DEFAULT 0,
    refusals INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS listings (
    id TEXT PRIMARY KEY,
    seller_id TEXT,
    title TEXT,
    pitch TEXT,
    rules_json TEXT,
    fingerprint TEXT,
    price_cents INTEGER,
    probation_s INTEGER,
    min_return_bps INTEGER,
    active INTEGER DEFAULT 1,
    created_at INTEGER
);
CREATE TABLE IF NOT EXISTS purchases (
    id TEXT PRIMARY KEY,
    listing_id TEXT,
    buyer_token_hash TEXT,
    buyer_email TEXT,
    buyer_payer_id TEXT,
    status TEXT,
    amount_cents INTEGER,
    fee_cents INTEGER,
    paypal_order_id TEXT,
    paypal_authorization_id TEXT,
    paypal_capture_id TEXT,
    paypal_payout_batch_id TEXT,
    payout_status TEXT,
    run_id INTEGER,
    verdict_json TEXT,
    license_key TEXT,
    error TEXT,
    created_at INTEGER,
    updated_at INTEGER,
    via TEXT DEFAULT 'web'
);
CREATE TABLE IF NOT EXISTS ledger (
    seq INTEGER PRIMARY KEY,
    at INTEGER,
    kind TEXT,
    subject TEXT,
    data_json TEXT,
    prev_hash TEXT,
    hash TEXT
);
CREATE TABLE IF NOT EXISTS webhook_events (
    id TEXT PRIMARY KEY,
    event_type TEXT,
    resource_id TEXT,
    verified INTEGER,
    received_at INTEGER,
    body_json TEXT
);
CREATE INDEX IF NOT EXISTS runs_seller ON runs(seller_id);
CREATE INDEX IF NOT EXISTS runs_status ON runs(status);
CREATE INDEX IF NOT EXISTS ledger_subject ON ledger(subject);
CREATE INDEX IF NOT EXISTS purchases_order ON purchases(paypal_order_id);
"""


def connect(path: str | Path | None = None) -> sqlite3.Connection:
    target = str(path or get_settings().database_path)
    conn = sqlite3.connect(target, check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    if target != ":memory:":
        conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    return conn


def get_db() -> sqlite3.Connection:
    global _connection
    with DB_LOCK:
        if _connection is None:
            _connection = connect()
        return _connection


def reset_db(path: str | Path | None = ":memory:") -> sqlite3.Connection:
    global _connection
    with DB_LOCK:
        if _connection is not None:
            _connection.close()
        _connection = connect(path)
        return _connection


def rows(sql: str, params: tuple = ()) -> list[dict]:
    with DB_LOCK:
        return [dict(r) for r in get_db().execute(sql, params).fetchall()]


def one(sql: str, params: tuple = ()) -> dict | None:
    found = rows(sql, params)
    return found[0] if found else None


def execute(sql: str, params: tuple = ()) -> int:
    with DB_LOCK:
        cursor = get_db().execute(sql, params)
        return cursor.lastrowid
