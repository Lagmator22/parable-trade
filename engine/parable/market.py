from parable import ledger, referee, runs
from parable.db import DB_LOCK, one
from parable.errors import MarketError
from parable.listing_views import list_listings, listing_detail, listing_summary
from parable.listings import (
    attach_benchmark,
    create_listing,
    ensure_tracks,
    listing_runs,
    pause_listing,
    poll_tracks,
    resume_listing,
    summarize,
    totals_by_status,
)
from parable.purchase_views import get_purchase
from parable.purchases import (
    cancel_purchase,
    cancel_unapproved,
    confirm_approval,
    retry_settlement,
    start_cancel_loop,
    start_purchase,
)
from parable.settlement import on_run_ended, settle_pending, update_purchase

__all__ = [
    "MarketError",
    "attach_benchmark",
    "cancel_purchase",
    "cancel_unapproved",
    "confirm_approval",
    "create_listing",
    "ensure_tracks",
    "find_purchase_by_order",
    "get_purchase",
    "install",
    "list_listings",
    "listing_detail",
    "listing_runs",
    "listing_summary",
    "market_stats",
    "on_webhook",
    "pause_listing",
    "poll_tracks",
    "resume_listing",
    "retry_settlement",
    "settle_pending",
    "start_cancel_loop",
    "start_purchase",
]

PAYOUT_FAILURES = ("DENIED", "FAILED", "UNCLAIMED", "RETURNED", "BLOCKED")


def install(manager: runs.RunManager) -> None:
    if on_run_ended not in manager.listeners:
        manager.add_end_listener(on_run_ended)
    manager.add_poll_hook(poll_tracks)


def find_purchase_by_order(order_id: str) -> dict | None:
    return one("SELECT * FROM purchases WHERE paypal_order_id = ?", (order_id,))


def count(sql: str) -> int:
    return one(sql)["n"]


def market_stats() -> dict:
    totals = summarize(totals_by_status())
    alive = referee.list_runs(status="alive", limit=100_000)
    return {
        "listings": count("SELECT COUNT(*) AS n FROM listings WHERE active = 1"),
        "sellers": count("SELECT COUNT(*) AS n FROM sellers"),
        "agents": count("SELECT COUNT(*) AS n FROM agents"),
        "proofs": count("SELECT COUNT(*) AS n FROM proofs"),
        "reruns": count("SELECT COUNT(*) AS n FROM proofs WHERE kind = 'rerun'"),
        "runs_alive": len(alive),
        "probations_running": sum(run["purpose"] == "probation" for run in alive),
        "tracks_running": sum(run["purpose"] == "track" for run in alive),
        "passed": totals["passed"],
        "failed": totals["failed"],
        "held_cents": totals["held_cents"],
        "captured_cents": totals["captured_cents"],
        "voided_cents": totals["voided_cents"],
        "paid_out_cents": totals["paid_out_cents"],
        "ledger_head": ledger.head(),
    }


def purchase_for_resource(event_type: str, resource: dict) -> dict | None:
    header = resource.get("batch_header") or {}
    item = resource.get("payout_item") or {}
    lookups = (
        ("paypal_capture_id", resource.get("id") if "CAPTURE" in event_type else None),
        ("paypal_authorization_id", resource.get("id") if "AUTHORIZATION" in event_type else None),
        ("paypal_payout_batch_id", header.get("payout_batch_id") or resource.get("payout_batch_id")),
        ("id", str(item.get("sender_item_id") or "").removesuffix("-payout") or None),
    )
    for column, value in lookups:
        found = one(f"SELECT * FROM purchases WHERE {column} = ?", (value,)) if value else None
        if found:
            return found
    return None


def payout_status_from(event_type: str, resource: dict) -> str | None:
    if event_type.startswith("PAYMENT.PAYOUTSBATCH"):
        return (resource.get("batch_header") or {}).get("batch_status") or event_type.rsplit(".", 1)[-1]
    if event_type.startswith("PAYMENT.PAYOUTS-ITEM"):
        return resource.get("transaction_status") or event_type.rsplit(".", 1)[-1]
    return None


def reconcile(purchase: dict, event_type: str, resource: dict) -> None:
    payout_status = payout_status_from(event_type, resource)
    with DB_LOCK:
        if payout_status:
            update_purchase(purchase["id"], payout_status=payout_status)
            if payout_status in PAYOUT_FAILURES:
                update_purchase(purchase["id"], error=f"payout {payout_status.lower()}")
        elif event_type == "PAYMENT.CAPTURE.DENIED" and purchase["paypal_capture_id"] == resource.get("id"):
            update_purchase(purchase["id"], status="error", paypal_capture_id=None, error="capture denied by PayPal")


def on_webhook(event_type: str, resource: dict) -> None:
    purchase = purchase_for_resource(event_type, resource)
    if purchase:
        reconcile(purchase, event_type, resource)
    ledger.append("webhook.received", f"purchase:{purchase['id']}" if purchase else "webhook", {
        "event_type": event_type, "resource_id": str(resource.get("id", "")),
        "purchase_id": purchase["id"] if purchase else None})
