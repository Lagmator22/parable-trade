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
CREATE TABLE IF NOT EXISTS agents (
    id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL,
    name TEXT NOT NULL,
    symbol TEXT NOT NULL,
    interval TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    latest_version_id TEXT,
    created_at INTEGER,
    updated_at INTEGER
);
CREATE TABLE IF NOT EXISTS agent_versions (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    n INTEGER NOT NULL,
    name TEXT,
    summary TEXT,
    spec_json TEXT NOT NULL,
    spec_hash TEXT NOT NULL,
    steps_text TEXT,
    built_by TEXT,
    created_at INTEGER,
    UNIQUE (agent_id, n)
);
CREATE TABLE IF NOT EXISTS datasets (
    id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL,
    name TEXT,
    interval TEXT,
    quote TEXT DEFAULT 'USD',
    bars INTEGER,
    start_t REAL,
    end_t REAL,
    data_hash TEXT,
    bars_json TEXT,
    created_at INTEGER
);
CREATE TABLE IF NOT EXISTS bar_sets (
    data_hash TEXT PRIMARY KEY,
    bars_json TEXT NOT NULL,
    created_at INTEGER
);
CREATE TABLE IF NOT EXISTS proofs (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    version_id TEXT NOT NULL,
    spec_hash TEXT NOT NULL,
    listing_id TEXT,
    requester_id TEXT,
    claim_proof_id TEXT,
    matched INTEGER,
    symbol TEXT,
    interval TEXT,
    quote TEXT,
    start_t REAL,
    end_t REAL,
    bars INTEGER,
    data_hash TEXT,
    source_kind TEXT,
    engine_version TEXT,
    metrics_json TEXT,
    curve_json TEXT,
    trades_json TEXT,
    markers_json TEXT,
    trades_count INTEGER,
    result_hash TEXT,
    ledger_seq INTEGER,
    created_at INTEGER
);
CREATE TABLE IF NOT EXISTS benchmarks (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    steps_text TEXT,
    symbol TEXT,
    interval TEXT,
    data_hash TEXT,
    result_json TEXT,
    created_at INTEGER
);
CREATE TABLE IF NOT EXISTS run_points (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    t INTEGER NOT NULL,
    equity INTEGER NOT NULL,
    price INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS ai_usage (
    visitor TEXT NOT NULL,
    day TEXT NOT NULL,
    n INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (visitor, day)
);
CREATE INDEX IF NOT EXISTS runs_seller ON runs(seller_id);
CREATE INDEX IF NOT EXISTS runs_status ON runs(status);
CREATE INDEX IF NOT EXISTS ledger_subject ON ledger(subject);
CREATE INDEX IF NOT EXISTS purchases_order ON purchases(paypal_order_id);
"""


NEW_COLUMNS = {
    "runs": {
        "version_id": "TEXT",
        "spec_hash": "TEXT",
        "symbol": "TEXT",
        "interval": "TEXT",
        "quote": "TEXT",
        "units": "INTEGER DEFAULT 0",
        "entry_price": "INTEGER DEFAULT 0",
        "high_water": "INTEGER DEFAULT 0",
        "last_bar_t": "INTEGER DEFAULT 0",
    },
    "listings": {
        "version_id": "TEXT",
        "mode": "TEXT DEFAULT 'hold'",
        "trial_s": "INTEGER DEFAULT 0",
        "max_loss_bps": "INTEGER DEFAULT 300",
        "proof_id": "TEXT",
        "benchmark_id": "TEXT",
        "allow_test_drive": "INTEGER DEFAULT 1",
        "symbol": "TEXT",
        "interval": "TEXT",
        "track_run_id": "INTEGER",
    },
    "purchases": {
        "buyer_id": "TEXT",
        "mode": "TEXT DEFAULT 'hold'",
        "version_id": "TEXT",
    },
}

NEW_INDEXES = """
CREATE INDEX IF NOT EXISTS agents_owner ON agents(owner_id);
CREATE INDEX IF NOT EXISTS versions_agent ON agent_versions(agent_id);
CREATE INDEX IF NOT EXISTS versions_hash ON agent_versions(spec_hash);
CREATE INDEX IF NOT EXISTS datasets_owner ON datasets(owner_id);
CREATE INDEX IF NOT EXISTS proofs_version ON proofs(version_id);
CREATE INDEX IF NOT EXISTS proofs_listing ON proofs(listing_id, kind);
CREATE INDEX IF NOT EXISTS benchmarks_agent ON benchmarks(agent_id);
CREATE INDEX IF NOT EXISTS run_points_run ON run_points(run_id, t);
CREATE INDEX IF NOT EXISTS listings_version ON listings(version_id);
CREATE INDEX IF NOT EXISTS purchases_buyer ON purchases(buyer_id);
CREATE INDEX IF NOT EXISTS runs_version ON runs(version_id);
"""


def ensure_columns(conn: sqlite3.Connection, table: str, columns: dict[str, str]) -> list[str]:
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    added = []
    for name, ddl in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
            added.append(name)
    return added


def connect(path: str | Path | None = None) -> sqlite3.Connection:
    target = str(path or get_settings().database_path)
    conn = sqlite3.connect(target, check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    if target != ":memory:":
        conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    for table, columns in NEW_COLUMNS.items():
        ensure_columns(conn, table, columns)
    conn.executescript(NEW_INDEXES)
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
