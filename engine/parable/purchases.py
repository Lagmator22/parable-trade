import hashlib
import json
import logging
import secrets
import threading
import time

from parable import ledger, runs, settlement
from parable.config import get_settings
from parable.db import DB_LOCK, execute, rows
from parable.errors import MarketError
from parable.listings import listing_row
from parable.models import BotRules
from parable.paypal import get_paypal
from parable.settlement import load_purchase, purchase_lock, update_purchase

log = logging.getLogger("parable.purchases")

VIAS = ("web", "agent")
APPROVAL_WINDOW_S = 3 * 3600
CANCEL_LOOP_EVERY_S = 300
BPS = 10_000


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def fee_for(amount_cents: int) -> int:
    return min(amount_cents, amount_cents * get_settings().platform_fee_bps // BPS)


def start_purchase(listing_id: str, via: str = "web") -> dict:
    if via not in VIAS:
        raise MarketError(f"via must be one of {', '.join(VIAS)}")
    listing = listing_row(listing_id)
    if not listing["active"]:
        raise MarketError("this listing is paused", 409)
    purchase_id = "p_" + secrets.token_hex(6)
    base = get_settings().public_base_url.rstrip("/")
    order = get_paypal().create_order(
        listing["price_cents"], f"Parable bot: {listing['title']}"[:127], purchase_id,
        f"{base}/paypal/return?purchase={purchase_id}", f"{base}/paypal/cancel?purchase={purchase_id}")
    token = secrets.token_urlsafe(24)
    fee = fee_for(listing["price_cents"])
    now = int(time.time())
    with DB_LOCK:
        execute(
            "INSERT INTO purchases (id, listing_id, buyer_token_hash, status, amount_cents, fee_cents,"
            " paypal_order_id, created_at, updated_at, via) VALUES (?,?,?,'created',?,?,?,?,?,?)",
            (purchase_id, listing_id, hash_token(token), listing["price_cents"], fee, order["id"], now, now, via))
        ledger.append("purchase.created", f"purchase:{purchase_id}", {
            "listing_id": listing_id, "amount_cents": listing["price_cents"], "fee_cents": fee, "via": via,
            "paypal_order_id": order["id"]})
    return {"purchase_id": purchase_id, "buyer_token": token, "paypal_order_id": order["id"],
            "approve_url": order["approve_url"]}


def begin_probation(purchase: dict) -> None:
    listing = listing_row(purchase["listing_id"])
    rules = BotRules.model_validate(json.loads(listing["rules_json"]))
    try:
        run = runs.get_manager().start(
            listing["seller_id"], rules, "probation", f"{listing['title']} (probation)",
            listing_id=listing["id"], purchase_id=purchase["id"])
    except Exception as err:
        log.exception("could not start probation for %s", purchase["id"])
        update_purchase(purchase["id"], status="error", error=f"probation did not start: {type(err).__name__}")
        return
    with DB_LOCK:
        update_purchase(purchase["id"], status="probation", run_id=run["id"], error=None)
        ledger.append("purchase.probation_started", f"purchase:{purchase['id']}", {
            "run_id": run["id"], "expires_at": run["expires_at"], "fingerprint": run["fingerprint"]})


def confirm_approval(purchase_id: str, order_id: str) -> dict:
    with purchase_lock(purchase_id):
        purchase = load_purchase(purchase_id)
        if order_id != purchase["paypal_order_id"]:
            raise MarketError("order does not belong to this purchase", 400)
        if purchase["status"] == "cancelled":
            raise MarketError("this purchase was cancelled", 409)
        if purchase["status"] != "created":
            return purchase
        authorization = get_paypal().authorize_order(order_id)
        with DB_LOCK:
            update_purchase(purchase_id, status="authorized",
                            paypal_authorization_id=authorization["authorization_id"],
                            buyer_email=authorization.get("payer_email") or None,
                            buyer_payer_id=authorization.get("payer_id") or None)
            ledger.append("purchase.authorized", f"purchase:{purchase_id}", {
                "authorization_id": authorization["authorization_id"], "amount_cents": purchase["amount_cents"],
                "expiration_time": authorization.get("expiration_time", "")})
        begin_probation(load_purchase(purchase_id))
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
