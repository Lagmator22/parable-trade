import json

from parable import referee
from parable.db import one, rows
from parable.lab import markets
from parable.lab.backtest import downsample
from parable.lab.consts import SPARKLINE_MAX
from parable.listings import listing_row, summarize, totals_by_listing, totals_by_status
from parable.run_views import public_run

HEADLINE_KEYS = ("total_return_pct", "benchmark_return_pct", "max_drawdown_pct", "sharpe", "win_rate_pct", "trades")
STAT_KEYS = ("purchases", "passed", "failed", "held_cents", "paid_out_cents")
DETAIL_PROOFS = 20
DETAIL_RUNS = 10
KIND_BY_PROVIDER = {"fx": "forex", "mfapi": "funds", "upload": "mine"}
MICRO = 1_000_000
PRICE_SCALE = 10**8


def asset_kind(symbol: str) -> str:
    try:
        return markets.symbol_info(symbol).kind
    except Exception:
        provider, _, code = str(symbol).partition(":")
        if provider == "binance":
            return "gold" if code == "PAXGUSDT" else "crypto"
        return KIND_BY_PROVIDER.get(provider, "stocks")


def data_info(proof: dict) -> dict:
    return {"symbol": proof["symbol"], "interval": proof["interval"], "start": proof["start_t"],
            "end": proof["end_t"], "bars": proof["bars"], "data_hash": proof["data_hash"],
            "source_kind": proof["source_kind"], "quote": proof["quote"]}


def headline_of(metrics: dict) -> dict:
    return {key: metrics.get(key) for key in HEADLINE_KEYS}


def seller_summaries() -> dict[str, dict]:
    return {row["id"]: {"id": row["id"], "name": row["name"], "verified": bool(row["verified"])}
            for row in rows("SELECT id, name, verified FROM sellers")}


def unknown_seller(seller_id: str) -> dict:
    return {"id": seller_id, "name": "Unknown seller", "verified": False}


def rerun_counts(listing_id: str) -> dict:
    found = one("SELECT COUNT(*) AS n, COALESCE(SUM(matched), 0) AS ok FROM proofs"
                " WHERE listing_id = ? AND kind = 'rerun'", (listing_id,))
    return {"count": found["n"], "matched": int(found["ok"])}


def track_view(listing: dict) -> dict | None:
    all_runs = rows("SELECT id, status, cause FROM runs WHERE listing_id = ? AND purpose = 'track'"
                    " ORDER BY id DESC", (listing["id"],))
    if not all_runs:
        return None
    current = referee.get_run(listing["track_run_id"] or all_runs[0]["id"])
    price = referee.view_price(current)
    count = one("SELECT COUNT(*) AS n FROM run_points WHERE run_id = ?", (current["id"],))["n"]
    start = current["start_cash_usd"]
    return {
        "run_id": current["id"], "status": current["status"], "since": current["started_at"],
        "seconds": current["lifetime_s"], "equity_pct": round((current["equity_usd"] / start - 1) * 100, 4),
        "start_equity": start / MICRO, "equity": current["equity_usd"] / MICRO,
        "price": price / PRICE_SCALE if price else None, "points": count, "runs_total": len(all_runs),
        "runs_ended_early": sum(run["status"] == "dead" and run["cause"] not in ("expired", "paused")
                                for run in all_runs), "quote": current["quote"],
    }


def public_view(row: dict, sellers: dict, totals: dict, records: dict) -> dict:
    proof = one("SELECT * FROM proofs WHERE id = ?", (row["proof_id"],)) or {}
    version = one("SELECT spec_hash, built_by FROM agent_versions WHERE id = ?", (row["version_id"],)) or {}
    metrics = json.loads(proof.get("metrics_json") or "{}")
    curve = json.loads(proof.get("curve_json") or "[]")
    seller_id = row["seller_id"]
    if seller_id not in records:
        records[seller_id] = referee.seller_record(seller_id)
    stats = summarize(totals)
    return {
        "id": row["id"], "title": row["title"], "pitch": row["pitch"], "price_cents": row["price_cents"],
        "mode": row["mode"], "trial_s": row["trial_s"], "min_return_bps": row["min_return_bps"],
        "max_loss_bps": row["max_loss_bps"], "allow_test_drive": bool(row["allow_test_drive"]),
        "symbol": row["symbol"], "interval": row["interval"], "quote": proof.get("quote", ""),
        "kind": asset_kind(row["symbol"]), "active": bool(row["active"]), "created_at": row["created_at"],
        "built_by": version.get("built_by", ""), "spec_hash": version.get("spec_hash", ""),
        "headline": headline_of(metrics), "sparkline": downsample(curve, SPARKLINE_MAX),
        "data": data_info(proof) if proof else None, "proof_id": row["proof_id"], "track": track_view(row),
        "reruns": rerun_counts(row["id"]), "seller": sellers.get(seller_id) or unknown_seller(seller_id),
        "seller_record": records[seller_id], "stats": {key: stats[key] for key in STAT_KEYS},
    }


def listing_summary(listing_id: str) -> dict:
    return public_view(listing_row(listing_id), seller_summaries(), totals_by_status(listing_id), {})


def benchmark_public(benchmark_id: str | None) -> dict | None:
    found = one("SELECT result_json FROM benchmarks WHERE id = ?", (benchmark_id,)) if benchmark_id else None
    if found is None:
        return None
    result = json.loads(found["result_json"])
    rows_ = [{"model": r["model"], "ok": r["ok"], "metrics": r.get("metrics"), "curve": r.get("curve") or [],
              "spec_hash": r.get("spec_hash")} for r in result.get("rows", [])]
    return {"id": result["id"], "agent_id": result["agent_id"], "data": result["data"],
            "buy_and_hold": result["buy_and_hold"], "rows": rows_}


def listing_detail(listing_id: str) -> dict:
    from parable import proofs

    row = listing_row(listing_id)
    base = public_view(row, seller_summaries(), totals_by_status(listing_id), {})
    claim = one("SELECT * FROM proofs WHERE id = ?", (row["proof_id"],))
    recent = rows("SELECT * FROM proofs WHERE listing_id = ? AND kind IN ('rerun', 'testdrive')"
                  " ORDER BY created_at DESC, id DESC LIMIT ?", (listing_id, DETAIL_PROOFS))
    return {
        **base,
        "proof": proofs.proof_view(claim, owner=False),
        "benchmark": benchmark_public(row["benchmark_id"]),
        "proofs": [proofs.proof_view(proof, owner=False) for proof in recent],
        "recent_runs": [public_run(run) for run in recent_runs(listing_id)],
    }


def recent_runs(listing_id: str) -> list[dict]:
    found = rows("SELECT id FROM runs WHERE listing_id = ? ORDER BY id DESC LIMIT ?", (listing_id, DETAIL_RUNS))
    return [referee.get_run(row["id"]) for row in found]


def sort_key(sort: str):
    if sort == "return":
        return lambda item: -(item["headline"].get("total_return_pct") or 0)
    if sort == "price":
        return lambda item: item["price_cents"]
    return lambda item: -item["created_at"]


def list_listings(kind: str | None = None, mode: str | None = None, sort: str = "new",
                  include_paused: bool = False) -> list[dict]:
    where = "" if include_paused else "WHERE active = 1"
    found = rows(f"SELECT * FROM listings {where} ORDER BY created_at DESC, id")
    sellers, totals, records = seller_summaries(), totals_by_listing(), {}
    views = [public_view(row, sellers, totals.get(row["id"], {}), records) for row in found if row["version_id"]]
    views = [v for v in views if (kind in (None, "", "all") or v["kind"] == kind) and (not mode or v["mode"] == mode)]
    return sorted(views, key=sort_key(sort))
