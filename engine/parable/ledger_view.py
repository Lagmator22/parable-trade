from parable import ledger
from parable.db import one
from parable.run_views import HIDDEN_FOR_OTHERS, run_visible

HIDDEN_RUN_DATA = (*HIDDEN_FOR_OTHERS, "name", "rules")
HIDDEN_MONEY_DATA = ("run_id", "purchase_id", "capture_id", "authorization_id", "payout_batch_id", "resource_id",
                     "seller_id", "buyer_id", "buyer_email", "payer_id", "payer_email", "error")
SCAN_BATCHES = 8


def run_row(run_id: str, cache: dict) -> dict | None:
    if run_id not in cache:
        cache[run_id] = one("SELECT id, seller_id, listing_id, purpose FROM runs WHERE id = ?", (run_id,))
    return cache[run_id]


def without(entry: dict, keys: tuple, subject: str | None = None) -> dict:
    data = {k: v for k, v in entry["data"].items() if k not in keys}
    return {**entry, "subject": subject or entry["subject"], "data": data, "redacted": True}


def shown_entry(entry: dict, viewer: str | None, cache: dict) -> dict | None:
    kind, _, ident = entry["subject"].partition(":")
    if kind == "run":
        run = run_row(ident, cache)
        if run is None or not run_visible(run, viewer):
            return None
        if run["purpose"] == "track" or viewer == run["seller_id"]:
            return entry
        return without(entry, HIDDEN_RUN_DATA)
    if kind == "purchase":
        return without(entry, HIDDEN_MONEY_DATA, "purchase")
    if entry["kind"].startswith(("payment.", "payout.")):
        return without(entry, HIDDEN_MONEY_DATA)
    return entry


def redact_entries(found: list[dict], viewer: str | None, cache: dict | None = None) -> list[dict]:
    cache = {} if cache is None else cache
    shown = (shown_entry(entry, viewer, cache) for entry in found)
    return [entry for entry in shown if entry is not None]


def public_entries(viewer: str | None, subject: str | None, kind: str | None, limit: int,
                   before: int | None) -> list[dict]:
    cache: dict = {}
    out: list[dict] = []
    cursor = before
    for _ in range(SCAN_BATCHES):
        batch = ledger.entries(subject=subject, kind=kind, limit=limit, before_seq=cursor)
        out += redact_entries(batch, viewer, cache)
        if len(out) >= limit or len(batch) < limit:
            break
        cursor = batch[-1]["seq"]
    return out[:limit]
