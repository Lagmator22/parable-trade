import hashlib
import hmac
import json

from parable import ledger, referee, runs
from parable.db import DB_LOCK, one, rows
from parable.errors import MarketError
from parable.listings import (
    ListingInput,
    create_listing,
    get_listing,
    list_listings,
    listing_runs,
    listing_summary,
    pause_listing,
    start_practice,
    summarize,
    totals_by_status,
)
from parable.purchases import (
    cancel_purchase,
    cancel_unapproved,
    confirm_approval,
    retry_settlement,
    start_cancel_loop,
    start_purchase,
)
from parable.settlement import load_purchase, on_run_ended, settle_pending, update_purchase

__all__ = [
    "ListingInput",
    "MarketError",
    "cancel_purchase",
    "cancel_unapproved",
    "confirm_approval",
    "create_listing",
    "find_purchase_by_order",
    "get_listing",
    "get_purchase",
    "install",
    "list_listings",
    "listing_runs",
    "market_stats",
    "on_webhook",
    "pause_listing",
    "retry_settlement",
    "settle_pending",
    "start_cancel_loop",
    "start_practice",
    "start_purchase",
]

TIMELINE_TRADES = 20
TIMELINE_ENTRIES = 500
PAYOUT_FAILURES = ("DENIED", "FAILED", "UNCLAIMED", "RETURNED", "BLOCKED")
LICENSE_STATUSES = ("captured", "paid_out")
LICENSE_INSTRUCTIONS = (
    "Run this bot with the rules above. The fingerprint identifies exactly what was tested on probation. "
    "Keep the license key private."
)


def install(manager: runs.RunManager) -> None:
    if on_run_ended not in manager.listeners:
        manager.add_end_listener(on_run_ended)


def mask_id(value: str | None) -> str:
    return f"***{value[-6:]}" if value else ""


def find_purchase_by_order(order_id: str) -> dict | None:
    return one("SELECT * FROM purchases WHERE paypal_order_id = ?", (order_id,))


def token_matches(purchase: dict, buyer_token: str | None) -> bool:
    if not buyer_token:
        return False
    supplied = hashlib.sha256(buyer_token.encode()).hexdigest()
    return hmac.compare_digest(supplied, purchase["buyer_token_hash"] or "")


def timeline_for(purchase_id: str, run_id: int | None) -> list[dict]:
    entries = ledger.entries(subject=f"purchase:{purchase_id}", limit=TIMELINE_ENTRIES)
    if run_id:
        entries += ledger.entries(subject=f"run:{run_id}", limit=TIMELINE_ENTRIES)
    trades = [entry for entry in entries if entry["kind"] == "run.trade"][:TIMELINE_TRADES]
    others = [entry for entry in entries if entry["kind"] != "run.trade"]
    return sorted(trades + others, key=lambda entry: entry["seq"])


def public_run(purchase: dict) -> dict | None:
    if not purchase["run_id"]:
        return None
    run = referee.get_run(purchase["run_id"])
    run.pop("rules_json", None)
    return run


def license_for(purchase: dict, listing: dict) -> dict | None:
    if purchase["status"] not in LICENSE_STATUSES or not purchase["license_key"]:
        return None
    return {"key": purchase["license_key"], "bot": listing["rules"], "fingerprint": listing["fingerprint"],
            "instructions": LICENSE_INSTRUCTIONS}


def get_purchase(purchase_id: str, buyer_token: str | None = None) -> dict:
    purchase = load_purchase(purchase_id)
    listing = listing_summary(purchase["listing_id"])
    verdict = json.loads(purchase["verdict_json"]) if purchase["verdict_json"] else None
    view = {
        "id": purchase["id"],
        "status": purchase["status"],
        "via": purchase["via"],
        "listing": listing,
        "amount_cents": purchase["amount_cents"],
        "fee_cents": purchase["fee_cents"],
        "payout_cents": purchase["amount_cents"] - purchase["fee_cents"],
        "paypal_order_id": mask_id(purchase["paypal_order_id"]),
        "paypal_authorization_id": mask_id(purchase["paypal_authorization_id"]),
        "paypal_capture_id": mask_id(purchase["paypal_capture_id"]),
        "paypal_payout_batch_id": mask_id(purchase["paypal_payout_batch_id"]),
        "payout_status": purchase["payout_status"] or "",
        "min_return_bps": listing["min_return_bps"],
        "threshold": {"min_return_bps": listing["min_return_bps"], "max_loss_bps": listing["rules"]["max_loss_bps"]},
        "run": public_run(purchase),
        "verdict": verdict,
        "timeline": timeline_for(purchase["id"], purchase["run_id"]),
        "error": purchase["error"] or "",
        "created_at": purchase["created_at"],
        "updated_at": purchase["updated_at"],
        "license": None,
    }
    if token_matches(purchase, buyer_token):
        view["license"] = license_for(purchase, listing)
    return view


def market_stats() -> dict:
    totals = summarize(totals_by_status())
    alive = referee.list_runs(status="alive", limit=100_000)
    return {
        "listings": len(rows("SELECT id FROM listings WHERE active = 1")),
        "sellers": len(rows("SELECT id FROM sellers")),
        "runs_alive": len(alive),
        "probations_running": sum(run["purpose"] == "probation" for run in alive),
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
