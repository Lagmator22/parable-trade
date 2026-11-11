import logging
import secrets
import threading
import time

from parable import ledger, runs, settlement
from parable.config import get_settings
from parable.db import DB_LOCK, execute, one, rows
from parable.errors import LabError, MarketError
from parable.instant import finish_instant, refuse_self_purchase
from parable.listings import listing_row
from parable.live_symbols import require_live_symbol
from parable.paypal import PayPalError, get_paypal
from parable.settlement import load_purchase, purchase_lock, update_purchase

log = logging.getLogger("parable.purchases")

APPROVAL_WINDOW_S = 3 * 3600
CANCEL_LOOP_EVERY_S = 300
BPS = 10_000
INTENTS = {"hold": "AUTHORIZE", "instant": "CAPTURE"}


def fee_for(amount_cents: int) -> int:
    return min(amount_cents, amount_cents * get_settings().platform_fee_bps // BPS)


def start_purchase(listing_id: str, buyer_id: str, via: str = "web") -> dict:
    listing = listing_row(listing_id)
    if not listing["active"]:
        raise MarketError("this listing is paused", 409)
    if listing["seller_id"] == buyer_id:
        raise LabError(403, "self_purchase", "you cannot buy your own agent")
    purchase_id = "p_" + secrets.token_hex(6)
    base = get_settings().public_base_url.rstrip("/")
    order = get_paypal().create_order(
        listing["price_cents"], f"Parable agent: {listing['title']}"[:127], purchase_id,
        f"{base}/paypal/return?purchase={purchase_id}", f"{base}/paypal/cancel?purchase={purchase_id}",
        INTENTS[listing["mode"]])
    fee = fee_for(listing["price_cents"])
    now = int(time.time())
    with DB_LOCK:
        execute(
            "INSERT INTO purchases (id, listing_id, buyer_id, mode, version_id, status, amount_cents, fee_cents,"
            " paypal_order_id, created_at, updated_at, via) VALUES (?,?,?,?,?,'created',?,?,?,?,?,?)",
            (purchase_id, listing_id, buyer_id, listing["mode"], listing["version_id"], listing["price_cents"], fee,
             order["id"], now, now, via))
        ledger.append("purchase.created", f"purchase:{purchase_id}", {
            "listing_id": listing_id, "mode": listing["mode"], "amount_cents": listing["price_cents"],
            "fee_cents": fee, "via": via, "paypal_order_id": order["id"]})
    return {"purchase_id": purchase_id, "status": "created", "mode": listing["mode"],
            "paypal_order_id": order["id"], "approve_url": order["approve_url"]}


def begin_probation(purchase: dict) -> None:
    listing = listing_row(purchase["listing_id"])
    try:
        require_live_symbol(listing["symbol"], "a hold trial")
        run = runs.get_manager().start_for_version(
            listing["seller_id"], listing["version_id"], listing["symbol"], listing["interval"], "probation",
            f"{listing['title']} (trial)", max_loss_bps=listing["max_loss_bps"], lease_seconds=listing["trial_s"],
            listing_id=listing["id"], purchase_id=purchase["id"])
    except Exception as err:
        log.exception("could not start probation for %s", purchase["id"])
        detail = err.detail if isinstance(err, LabError) else type(err).__name__
        update_purchase(purchase["id"], status="error", error=f"trial did not start: {detail}"[:300])
        return
    with DB_LOCK:
        update_purchase(purchase["id"], status="probation", run_id=run["id"], error=None)
        ledger.append("purchase.probation_started", f"purchase:{purchase['id']}", {
            "run_id": run["id"], "expires_at": run["expires_at"], "spec_hash": run["spec_hash"]})


def seller_payer_id(listing: dict) -> str:
    return (one("SELECT paypal_payer_id FROM sellers WHERE id = ?", (listing["seller_id"],)) or {}).get(
        "paypal_payer_id") or ""


def confirm_hold(purchase: dict, listing: dict) -> None:
    require_live_symbol(listing["symbol"], "a hold trial")
    order_id = purchase["paypal_order_id"]
    authorization = get_paypal().authorize_order(order_id)
    payer_id = authorization.get("payer_id") or ""
    if payer_id and payer_id == seller_payer_id(listing):
        get_paypal().void_authorization(authorization["authorization_id"])
        with DB_LOCK:
            update_purchase(purchase["id"], status="cancelled", buyer_payer_id=payer_id)
            ledger.append("purchase.cancelled", f"purchase:{purchase['id']}", {"reason": "self_purchase"})
        raise LabError(403, "self_purchase", "you cannot buy your own agent")
    with DB_LOCK:
        update_purchase(purchase["id"], status="authorized",
                        paypal_authorization_id=authorization["authorization_id"],
                        buyer_email=authorization.get("payer_email") or None, buyer_payer_id=payer_id or None)
        ledger.append("purchase.authorized", f"purchase:{purchase['id']}", {
            "authorization_id": authorization["authorization_id"], "amount_cents": purchase["amount_cents"],
            "expiration_time": authorization.get("expiration_time", "")})
    begin_probation(load_purchase(purchase["id"]))


def confirm_instant(purchase: dict, listing: dict) -> None:
    order = get_paypal().get_order(purchase["paypal_order_id"])
    if order.get("status") not in ("APPROVED", "COMPLETED"):
        raise PayPalError(422, "ORDER_NOT_APPROVED", "payer has not approved the order")
    payer = order.get("payer") or {}
    payer_id = payer.get("payer_id") or ""
    if payer_id and payer_id == seller_payer_id(listing):
        refuse_self_purchase(purchase["id"])
    update_purchase(purchase["id"], buyer_payer_id=payer_id or None,
                    buyer_email=payer.get("email") or payer.get("email_address") or None)
    finish_instant(purchase["id"], allow_created=True)


def confirm_approval(purchase_id: str, order_id: str) -> dict:
    with purchase_lock(purchase_id):
        purchase = load_purchase(purchase_id)
        if order_id != purchase["paypal_order_id"]:
            raise MarketError("order does not belong to this purchase", 400)
        if purchase["status"] == "cancelled":
            raise MarketError("this purchase was cancelled", 409)
        if purchase["status"] != "created":
            return purchase
        listing = listing_row(purchase["listing_id"])
        if purchase["mode"] == "instant":
            confirm_instant(purchase, listing)
        else:
            confirm_hold(purchase, listing)
        return load_purchase(purchase_id)


def cancel_purchase(purchase_id: str) -> dict:
    with purchase_lock(purchase_id):
        purchase = load_purchase(purchase_id)
        if purchase["status"] != "created":
            return purchase
        with DB_LOCK:
            update_purchase(purchase_id, status="cancelled")
            ledger.append("purchase.cancelled", f"purchase:{purchase_id}", {"reason": "buyer did not approve"})
        return load_purchase(purchase_id)


def cancel_unapproved(max_age_s: int = APPROVAL_WINDOW_S) -> int:
    cutoff = int(time.time()) - max_age_s
    stale = rows("SELECT id FROM purchases WHERE status = 'created' AND created_at < ?", (cutoff,))
    for purchase in stale:
        cancel_purchase(purchase["id"])
    return len(stale)


def retry_settlement(purchase_id: str) -> dict:
    with purchase_lock(purchase_id):
        purchase = load_purchase(purchase_id)
        if purchase["status"] != "error":
            raise MarketError("this purchase has no error to retry", 409)
        if purchase["mode"] == "instant":
            return finish_instant(purchase_id)
        if purchase["verdict_json"]:
            return settlement.resume(purchase)
        if purchase["paypal_authorization_id"] and not purchase["run_id"]:
            begin_probation(purchase)
            return load_purchase(purchase_id)
        raise MarketError("nothing to retry yet", 409)


def cancel_loop(stop: threading.Event, every_s: float) -> None:
    while not stop.wait(every_s):
        try:
            cancel_unapproved()
        except Exception:
            log.exception("cancelling stale purchases failed")


def start_cancel_loop(every_s: float = CANCEL_LOOP_EVERY_S) -> threading.Event:
    stop = threading.Event()
    threading.Thread(target=cancel_loop, args=(stop, every_s), daemon=True, name="purchase-cancel-loop").start()
    return stop

