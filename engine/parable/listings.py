import logging
import secrets
import threading
import time

from parable import ledger, referee, runs
from parable.db import DB_LOCK, execute, one, rows
from parable.errors import LabError
from parable.live_symbols import is_live_symbol, require_instant_mode, require_live_symbol
from parable.models import NewListing

log = logging.getLogger("parable.listings")

ENSURE_EVERY_S = 60
SETTLED_STATUSES = ("created", "cancelled")
PASSED_STATUSES = ("passed", "captured", "paid_out")
FAILED_STATUSES = ("failed", "voided")
HELD_STATUSES = ("authorized", "probation", "passed", "failed")
CAPTURED_STATUSES = ("captured", "paid_out")

_ensure_lock = threading.Lock()
_last_ensure = [0.0]


def listing_row(listing_id: str) -> dict:
    row = one("SELECT * FROM listings WHERE id = ?", (listing_id,))
    if row is None:
        raise LabError(404, "not_found", "listing not found")
    return row


def owned_listing(owner_id: str, listing_id: str) -> dict:
    row = listing_row(listing_id)
    if row["seller_id"] != owner_id:
        raise LabError(403, "forbidden", "this is not your listing")
    return row


def version_context(owner_id: str, version_id: str) -> dict:
    found = one(
        "SELECT v.id AS version_id, v.agent_id, v.spec_hash, a.owner_id FROM agent_versions v"
        " JOIN agents a ON a.id = v.agent_id WHERE v.id = ?", (version_id,))
    if found is None:
        raise LabError(404, "not_found", "version not found")
    if found["owner_id"] != owner_id:
        raise LabError(403, "forbidden", "this is not your agent")
    return found


def headline_proof(version_id: str, proof_id: str) -> dict:
    proof = one("SELECT * FROM proofs WHERE id = ?", (proof_id,))
    if proof is None or proof["kind"] != "backtest" or proof["version_id"] != version_id:
        raise LabError(400, "bad_request", "proof_id must be a backtest proof of this exact version")
    return proof


def start_track(listing: dict) -> dict | None:
    if not is_live_symbol(listing["symbol"]):
        return None
    from parable.config import get_settings

    run = runs.get_manager().start_for_version(
        listing["seller_id"], listing["version_id"], listing["symbol"], listing["interval"], "track",
        f"{listing['title']} (live track)", max_loss_bps=listing["max_loss_bps"],
        lease_seconds=get_settings().track_lease_seconds, listing_id=listing["id"])
    with DB_LOCK:
        execute("UPDATE listings SET track_run_id = ? WHERE id = ?", (run["id"], listing["id"]))
    return run


def start_track_safely(listing: dict) -> None:
    try:
        start_track(listing)
    except Exception:
        log.exception("could not start the track run for listing %s", listing["id"])


def create_listing(owner_id: str, data: NewListing) -> dict:
    context = version_context(owner_id, data.version_id)
    proof = headline_proof(data.version_id, data.proof_id)
    require_instant_mode(proof["symbol"], data.mode)
    listing_id = "l_" + secrets.token_hex(5)
    title = data.title.strip()
    with DB_LOCK:
        execute(
            "INSERT INTO listings (id, seller_id, title, pitch, rules_json, fingerprint, price_cents, probation_s,"
            " min_return_bps, active, created_at, version_id, mode, trial_s, max_loss_bps, proof_id,"
            " allow_test_drive, symbol, interval) VALUES (?,?,?,?,'','',?,?,?,1,?,?,?,?,?,?,?,?,?)",
            (listing_id, owner_id, title, data.pitch.strip(), data.price_cents, data.trial_s, data.min_return_bps,
             int(time.time()), data.version_id, data.mode, data.trial_s, data.max_loss_bps, data.proof_id,
             int(data.allow_test_drive), proof["symbol"], proof["interval"]))
        execute("UPDATE agents SET status = 'listed', updated_at = ? WHERE id = ?",
                (int(time.time()), context["agent_id"]))
        ledger.append("listing.created", f"listing:{listing_id}", {
            "seller_id": owner_id, "version_id": data.version_id, "spec_hash": context["spec_hash"],
            "title": title, "mode": data.mode, "price_cents": data.price_cents, "trial_s": data.trial_s,
            "min_return_bps": data.min_return_bps, "max_loss_bps": data.max_loss_bps, "proof_id": data.proof_id,
            "result_hash": proof["result_hash"]})
    start_track_safely(listing_row(listing_id))
    return listing_row(listing_id)


def alive_track(listing_id: str) -> dict | None:
    return one("SELECT * FROM runs WHERE listing_id = ? AND purpose = 'track' AND status = 'alive'"
               " ORDER BY id DESC LIMIT 1", (listing_id,))


def pause_listing(owner_id: str, listing_id: str) -> dict:
    row = owned_listing(owner_id, listing_id)
    if row["active"]:
        with DB_LOCK:
            execute("UPDATE listings SET active = 0 WHERE id = ?", (listing_id,))
            ledger.append("listing.paused", f"listing:{listing_id}", {"seller_id": owner_id})
        track = alive_track(listing_id)
        if track:
            runs.get_manager().stop(track["id"], "paused")
    return listing_row(listing_id)


def resume_listing(owner_id: str, listing_id: str) -> dict:
    row = owned_listing(owner_id, listing_id)
    if not row["active"]:
        with DB_LOCK:
            execute("UPDATE listings SET active = 1 WHERE id = ?", (listing_id,))
            ledger.append("listing.resumed", f"listing:{listing_id}", {"seller_id": owner_id})
        if alive_track(listing_id) is None:
            start_track_safely(listing_row(listing_id))
    return listing_row(listing_id)


def attach_benchmark(owner_id: str, listing_id: str, benchmark_id: str) -> dict:
    row = owned_listing(owner_id, listing_id)
    found = one("SELECT b.id, b.owner_id, b.agent_id FROM benchmarks b WHERE b.id = ?", (benchmark_id,))
    context = one("SELECT agent_id FROM agent_versions WHERE id = ?", (row["version_id"],))
    if found is None or found["owner_id"] != owner_id or context is None or found["agent_id"] != context["agent_id"]:
        raise LabError(404, "not_found", "benchmark not found")
    with DB_LOCK:
        execute("UPDATE listings SET benchmark_id = ? WHERE id = ?", (benchmark_id, listing_id))
        ledger.append("listing.benchmark_attached", f"listing:{listing_id}", {"benchmark_id": benchmark_id})
    return listing_row(listing_id)


def ensure_tracks() -> int:
    started = 0
    for listing in rows("SELECT * FROM listings WHERE active = 1 AND version_id IS NOT NULL"):
        if is_live_symbol(listing["symbol"] or "") and alive_track(listing["id"]) is None:
            try:
                if start_track(listing):
                    started += 1
            except Exception:
                log.exception("could not restart the track run for listing %s", listing["id"])
    return started


def poll_tracks() -> None:
    with _ensure_lock:
        if time.monotonic() - _last_ensure[0] < ENSURE_EVERY_S and _last_ensure[0]:
            return
        _last_ensure[0] = time.monotonic()
    ensure_tracks()


def reset_throttle() -> None:
    _last_ensure[0] = 0.0


def require_probation_symbol(symbol: str) -> None:
    require_live_symbol(symbol, "a hold trial")


def totals_by_status(listing_id: str | None = None) -> dict[str, dict]:
    where, params = ("WHERE listing_id = ?", (listing_id,)) if listing_id else ("", ())
    found = rows(
        "SELECT status, COUNT(*) AS n, COALESCE(SUM(amount_cents), 0) AS amount, COALESCE(SUM(fee_cents), 0) AS fee"
        f" FROM purchases {where} GROUP BY status", params)
    return {row["status"]: row for row in found}


def totals_by_listing() -> dict[str, dict[str, dict]]:
    grouped: dict[str, dict[str, dict]] = {}
    for row in rows(
            "SELECT listing_id, status, COUNT(*) AS n, COALESCE(SUM(amount_cents), 0) AS amount,"
            " COALESCE(SUM(fee_cents), 0) AS fee FROM purchases GROUP BY listing_id, status"):
        grouped.setdefault(row["listing_id"], {})[row["status"]] = row
    return grouped


def summarize(by_status: dict[str, dict]) -> dict:
    def total(statuses: tuple[str, ...], field: str) -> int:
        return sum(by_status.get(status, {}).get(field, 0) for status in statuses)

    return {
        "purchases": sum(row["n"] for status, row in by_status.items() if status not in SETTLED_STATUSES),
        "passed": total(PASSED_STATUSES, "n"),
        "failed": total(FAILED_STATUSES, "n"),
        "held_cents": total(HELD_STATUSES, "amount"),
        "captured_cents": total(CAPTURED_STATUSES, "amount"),
        "voided_cents": total(("voided",), "amount"),
        "paid_out_cents": total(("paid_out",), "amount") - total(("paid_out",), "fee"),
    }


def listing_runs(listing_id: str, limit: int = 30) -> list[dict]:
    listing_row(listing_id)
    found = rows("SELECT id FROM runs WHERE listing_id = ? ORDER BY id DESC LIMIT ?", (listing_id, limit))
    return [referee.get_run(row["id"]) for row in found]



def listing_summary(listing_id: str) -> dict:
    from parable.listing_views import listing_summary as build

    return build(listing_id)
