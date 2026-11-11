import json
import re

from parable import ledger, referee
from parable.db import one
from parable.errors import LabError
from parable.lab.consts import ENGINE_VERSION
from parable.lab.spec import load_spec
from parable.listing_views import listing_summary
from parable.listings import listing_row
from parable.run_views import public_run
from parable.settlement import load_purchase

TIMELINE_TRADES = 20
TIMELINE_ENTRIES = 500
ENTITLED_STATUSES = ("captured", "paid_out")
RUN_HINT = ("Run it on Parable from My agents or load the JSON into any engine that implements the Parable "
            "formula language.")


def mask_id(value: str | None) -> str:
    return f"***{value[-6:]}" if value else ""


def is_entitled(purchase: dict) -> bool:
    if purchase["status"] in ENTITLED_STATUSES:
        return True
    return purchase["status"] == "error" and bool(purchase["paypal_capture_id"])


def buyer_purchase(purchase_id: str, buyer_id: str) -> dict:
    purchase = load_purchase(purchase_id)
    if purchase["buyer_id"] != buyer_id:
        raise LabError(404, "not_found", "purchase not found")
    return purchase


def entitled_purchase(purchase_id: str, buyer_id: str) -> dict:
    purchase = buyer_purchase(purchase_id, buyer_id)
    if not is_entitled(purchase):
        raise LabError(403, "not_entitled", "this purchase has not been paid yet")
    return purchase


def timeline_for(purchase_id: str, run_id: int | None) -> list[dict]:
    entries = ledger.entries(subject=f"purchase:{purchase_id}", limit=TIMELINE_ENTRIES)
    if run_id:
        entries += ledger.entries(subject=f"run:{run_id}", limit=TIMELINE_ENTRIES)
    trades = [entry for entry in entries if entry["kind"] == "run.trade"][:TIMELINE_TRADES]
    others = [entry for entry in entries if entry["kind"] != "run.trade"]
    return sorted(trades + others, key=lambda entry: entry["seq"])


def license_for(purchase: dict) -> dict | None:
    if not is_entitled(purchase) or not purchase["license_key"]:
        return None
    listing = listing_row(purchase["listing_id"])
    version = one("SELECT spec_hash, steps_text FROM agent_versions WHERE id = ?", (listing["version_id"],)) or {}
    return {"key": purchase["license_key"], "format": "parable-agent", "engine_version": ENGINE_VERSION,
            "spec_hash": version.get("spec_hash", ""), "spec": load_spec(listing["version_id"]).model_dump(),
            "steps_text": version.get("steps_text") or "", "proof_id": listing["proof_id"], "run_hint": RUN_HINT}


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "agent"


def license_download(purchase_id: str, buyer_id: str) -> tuple[str, str]:
    purchase = entitled_purchase(purchase_id, buyer_id)
    license_ = license_for(purchase)
    if license_ is None:
        raise LabError(403, "not_entitled", "no license has been issued yet")
    listing = listing_row(purchase["listing_id"])
    name = f"{slug(listing['title'])}-{license_['spec_hash'][:8]}.json"
    return name, json.dumps(license_, indent=2, sort_keys=True)


def purchase_view(purchase: dict) -> dict:
    listing = listing_summary(purchase["listing_id"])
    verdict = json.loads(purchase["verdict_json"]) if purchase["verdict_json"] else None
    run = referee.get_run(purchase["run_id"]) if purchase["run_id"] else None
    return {
        "id": purchase["id"], "status": purchase["status"], "mode": purchase["mode"], "listing": listing,
        "amount_cents": purchase["amount_cents"], "fee_cents": purchase["fee_cents"],
        "payout_cents": purchase["amount_cents"] - purchase["fee_cents"],
        "paypal_order_id": mask_id(purchase["paypal_order_id"]),
        "paypal_authorization_id": mask_id(purchase["paypal_authorization_id"]),
        "paypal_capture_id": mask_id(purchase["paypal_capture_id"]),
        "paypal_payout_batch_id": mask_id(purchase["paypal_payout_batch_id"]),
        "payout_status": purchase["payout_status"] or "",
        "threshold": {"min_return_bps": listing["min_return_bps"], "max_loss_bps": listing["max_loss_bps"]},
        "run": public_run(run) if run else None, "verdict": verdict,
        "timeline": timeline_for(purchase["id"], purchase["run_id"]), "error": purchase["error"] or "",
        "created_at": purchase["created_at"], "updated_at": purchase["updated_at"], "license": license_for(purchase),
    }


def get_purchase(purchase_id: str, buyer_id: str) -> dict:
    return purchase_view(buyer_purchase(purchase_id, buyer_id))
