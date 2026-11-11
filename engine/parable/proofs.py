import json
import secrets
import time

from parable import agents, db, guard, ledger
from parable.config import get_settings
from parable.errors import LabError
from parable.lab import markets, quota
from parable.lab.backtest import data_hash, run_backtest
from parable.lab.consts import INTERVAL_SECONDS, INTERVALS, MIN_BARS
from parable.lab.spec import load_spec, spec_hash
from parable.models import StrategySpec

KINDS = ("backtest", "rerun", "testdrive", "benchmark")
KEEP_BACKTESTS_PER_VERSION = 20
MAX_CHECKS_PER_LISTING_PER_DAY = 200
MAX_ANONYMOUS_CHECKS_PER_LISTING_PER_DAY = 200
MAX_ANONYMOUS_CHECKS_PER_IP_PER_LISTING_PER_DAY = 20


def keep_bars(bars: list, digest: str) -> None:
    db.execute("INSERT OR IGNORE INTO bar_sets (data_hash, bars_json, created_at) VALUES (?, ?, ?)",
               (digest, json.dumps(bars, separators=(",", ":")), int(time.time())))


def prune_backtests(version_id: str) -> None:
    with db.DB_LOCK:
        db.execute(
            "DELETE FROM proofs WHERE version_id = ? AND kind = 'backtest' AND id NOT IN"
            " (SELECT proof_id FROM listings WHERE proof_id IS NOT NULL) AND id NOT IN"
            " (SELECT id FROM proofs WHERE version_id = ? AND kind = 'backtest' ORDER BY created_at DESC, id DESC"
            " LIMIT ?)", (version_id, version_id, KEEP_BACKTESTS_PER_VERSION))
        prune_bar_sets()


def prune_bar_sets() -> None:
    db.execute("DELETE FROM bar_sets WHERE data_hash NOT IN (SELECT data_hash FROM proofs WHERE data_hash IS NOT NULL)"
               " AND data_hash NOT IN (SELECT data_hash FROM benchmarks WHERE data_hash IS NOT NULL)")


def load_bars(digest: str) -> list | None:
    row = db.one("SELECT bars_json FROM bar_sets WHERE data_hash = ?", (digest,))
    return json.loads(row["bars_json"]) if row else None


def store_proof(kind: str, version_id: str, spec: StrategySpec, result: dict, *, listing_id: str | None = None,
                requester_id: str | None = None, claim_proof_id: str | None = None, matched: bool | None = None,
                bars: list | None = None) -> dict:
    if kind not in KINDS:
        raise ValueError(f"unknown proof kind {kind}")
    info = result["data"]
    proof_id = "pf_" + secrets.token_hex(5)
    with db.DB_LOCK:
        if bars is not None:
            keep_bars(bars, info["data_hash"])
        db.execute(
            "INSERT INTO proofs (id, kind, version_id, spec_hash, listing_id, requester_id, claim_proof_id, matched,"
            " symbol, interval, quote, start_t, end_t, bars, data_hash, source_kind, engine_version, metrics_json,"
            " curve_json, trades_json, markers_json, trades_count, result_hash, ledger_seq, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULL,?)",
            (proof_id, kind, version_id, result.get("spec_hash") or spec_hash(spec), listing_id, requester_id,
             claim_proof_id, None if matched is None else int(matched), info["symbol"], info["interval"],
             info["quote"], info["start"], info["end"], info["bars"], info["data_hash"], info["source_kind"],
             result["engine_version"], json.dumps(result["metrics"]), json.dumps(result["curve"]),
             json.dumps(result["trades"]), json.dumps(result["markers"]), len(result["trades"]),
             result["result_hash"], int(time.time())))
        entry = ledger.append("proof.stored", f"proof:{proof_id}", {
            "kind": kind, "version_id": version_id, "spec_hash": result["spec_hash"],
            "result_hash": result["result_hash"], "data_hash": info["data_hash"], "listing_id": listing_id})
        db.execute("UPDATE proofs SET ledger_seq = ? WHERE id = ?", (entry["seq"], proof_id))
    return db.one("SELECT * FROM proofs WHERE id = ?", (proof_id,))


def by_of(row: dict) -> str:
    requester = row["requester_id"]
    if row["kind"] in ("backtest", "benchmark") or requester == agents.version_owner(row["version_id"]):
        return "seller"
    return "buyer" if requester and agents.entitled(requester, row["version_id"]) else "visitor"


def proof_view(row: dict, *, owner: bool) -> dict:
    matched = row["matched"]
    out = {
        "id": row["id"], "kind": row["kind"], "spec_hash": row["spec_hash"], "symbol": row["symbol"],
        "interval": row["interval"],
        "data": {"symbol": row["symbol"], "interval": row["interval"], "start": row["start_t"], "end": row["end_t"],
                 "bars": row["bars"], "data_hash": row["data_hash"], "source_kind": row["source_kind"],
                 "quote": row["quote"]},
        "metrics": json.loads(row["metrics_json"]), "curve": json.loads(row["curve_json"]),
        "trades_count": row["trades_count"], "engine_version": row["engine_version"],
        "result_hash": row["result_hash"], "ledger_seq": row["ledger_seq"],
        "matched": None if matched is None else bool(matched), "by": by_of(row), "created_at": row["created_at"],
        "assumptions": agents.version_assumptions(row["version_id"]), "verifiable": row["source_kind"] != "creator",
    }
    if owner:
        out.update(trades=json.loads(row["trades_json"]), markers=json.loads(row["markers_json"]),
                   version_id=row["version_id"])
    return out


def proof_row(proof_id: str) -> dict:
    row = db.one("SELECT * FROM proofs WHERE id = ?", (proof_id,))
    if row is None:
        raise LabError(404, "not_found", "no such proof")
    return row


def get_proof(proof_id: str, viewer_id: str | None) -> dict:
    row = proof_row(proof_id)
    owns = viewer_id is not None and agents.version_owner(row["version_id"]) == viewer_id
    public = db.one("SELECT 1 AS x FROM listings WHERE active = 1 AND (id = ? OR proof_id = ?) LIMIT 1",
                    (row["listing_id"] or "", proof_id))
    if not (owns or (viewer_id is not None and row["requester_id"] == viewer_id) or public):
        raise LabError(404, "not_found", "no such proof")
    return proof_view(row, owner=owns)


def listing_checks(listing_id: str, limit: int = 50) -> list[dict]:
    found = db.rows("SELECT * FROM proofs WHERE listing_id = ? AND kind IN ('rerun', 'testdrive')"
                    " ORDER BY created_at DESC, id DESC LIMIT ?", (listing_id, limit))
    return [proof_view(r, owner=False) for r in found]


def rate_check(requester_id: str, listing_id: str | None = None) -> None:
    quota.hit_with_address(f"proofs:{requester_id}", get_settings().rate_proofs_per_hour, 3600)
    if listing_id is None:
        return
    since = int(time.time()) - 86_400
    if requester_id.startswith("v_"):
        today = db.one("SELECT COUNT(*) AS n FROM proofs WHERE listing_id = ? AND substr(requester_id, 1, 2) = 'v_'"
                       " AND kind IN ('rerun', 'testdrive') AND created_at > ?", (listing_id, since))
        cap = MAX_ANONYMOUS_CHECKS_PER_LISTING_PER_DAY
    else:
        today = db.one("SELECT COUNT(*) AS n FROM proofs WHERE listing_id = ? AND requester_id = ?"
                       " AND kind IN ('rerun', 'testdrive') AND created_at > ?", (listing_id, requester_id, since))
        cap = MAX_CHECKS_PER_LISTING_PER_DAY
    if today["n"] >= cap:
        raise LabError(429, "rate_limited", "you checked this agent a lot today, try again tomorrow")
    if requester_id.startswith("v_"):
        source = quota.ip_visitor(guard.client_ip.get())
        quota.limiter.hit(f"checks:{source}:{listing_id}", MAX_ANONYMOUS_CHECKS_PER_IP_PER_LISTING_PER_DAY, 86_400)


def listing_row(listing_id: str) -> dict:
    row = db.one("SELECT * FROM listings WHERE id = ?", (listing_id,))
    if row is None or not row["active"]:
        raise LabError(404, "not_found", "no such listing")
    return row


def diff_of(claim: dict, rerun: dict) -> dict:
    keys = list(claim) + [k for k in rerun if k not in claim]
    return {k: {"claim": claim.get(k), "rerun": rerun.get(k)} for k in keys}


def rerun_listing(listing_id: str, requester_id: str, refetch: bool = False) -> dict:
    listing = listing_row(listing_id)
    rate_check(requester_id, listing_id)
    claim_row = proof_row(listing["proof_id"]) if listing["proof_id"] else None
    if claim_row is None:
        raise LabError(404, "not_found", "this listing has no proof to re-run")
    spec = load_spec(listing["version_id"])
    bars = load_bars(claim_row["data_hash"])
    if bars is None:
        raise LabError(404, "not_found", "the original data is no longer stored")
    fetched = refetch and claim_row["source_kind"] != "creator"
    match_data: bool | None = None
    if fetched:
        step = INTERVAL_SECONDS[claim_row["interval"]]
        fresh = markets.closed_candles(claim_row["symbol"], claim_row["interval"], claim_row["bars"],
                                claim_row["start_t"], claim_row["end_t"] + step)
        match_data = data_hash(fresh) == claim_row["data_hash"]
        bars = fresh
    if len(bars) < MIN_BARS:
        raise LabError(400, "bad_request", "not enough data to re-run")
    result = run_backtest(spec, bars, symbol=claim_row["symbol"], interval=claim_row["interval"],
                          quote=claim_row["quote"], source_kind=claim_row["source_kind"])
    same = result["result_hash"] == claim_row["result_hash"]
    stored = store_proof("rerun", listing["version_id"], spec, result, listing_id=listing_id,
                         requester_id=requester_id, claim_proof_id=claim_row["id"], matched=same)
    claim = proof_view(claim_row, owner=False)
    rerun = proof_view(stored, owner=False)
    return {"match": same, "claim": claim, "rerun": rerun, "diff": diff_of(claim["metrics"], rerun["metrics"]),
            "data_hash_match": match_data, "refetched": fetched}


def test_drive(listing_id: str, requester_id: str, symbol: str | None = None, interval: str | None = None,
               start: float | None = None, end: float | None = None) -> dict:
    listing = listing_row(listing_id)
    rate_check(requester_id, listing_id)
    if not listing["allow_test_drive"]:
        raise LabError(403, "test_drive_off", "the seller turned test drives off for this agent")
    claim_row = proof_row(listing["proof_id"]) if listing["proof_id"] else None
    spec = load_spec(listing["version_id"])
    symbol = (symbol or listing["symbol"] or spec.symbol).strip()
    interval = interval or listing["interval"] or spec.interval
    if symbol.startswith("upload:"):
        raise LabError(403, "forbidden", "uploaded data cannot be used for test drives")
    if interval not in INTERVALS:
        raise LabError(400, "bad_request", f"interval must be one of {', '.join(INTERVALS)}")
    bars = markets.closed_candles(symbol, interval, 2000, start, end)
    if len(bars) < MIN_BARS:
        raise LabError(400, "bad_request", f"only {len(bars)} bars are available, need at least {MIN_BARS}")
    result = run_backtest(spec.model_copy(update={"symbol": symbol, "interval": interval}), bars, symbol=symbol,
                          interval=interval, quote=markets.quote_currency(symbol),
                          source_kind=markets.source_kind(symbol))
    stored = store_proof("testdrive", listing["version_id"], spec.model_copy(update={"symbol": symbol,
                         "interval": interval}), result, listing_id=listing_id, requester_id=requester_id,
                         claim_proof_id=claim_row["id"] if claim_row else None)
    return {"proof": proof_view(stored, owner=False), "claim": proof_view(claim_row, owner=False) if claim_row else None}
