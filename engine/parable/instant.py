from parable import ledger
from parable.db import DB_LOCK
from parable.errors import LabError
from parable.paypal import get_paypal
from parable.settlement import (error_message, load_purchase, pay_seller, purchase_lock, record_capture,
                                update_purchase)


def cancel_for_self_purchase(purchase_id: str) -> None:
    with DB_LOCK:
        update_purchase(purchase_id, status="cancelled")
        ledger.append("purchase.cancelled", f"purchase:{purchase_id}", {"reason": "self_purchase"})


def refuse_self_purchase(purchase_id: str) -> None:
    cancel_for_self_purchase(purchase_id)
    raise LabError(403, "self_purchase", "you cannot buy your own agent")


def capture_order_once(purchase: dict) -> dict:
    if purchase["paypal_capture_id"]:
        return purchase
    result = get_paypal().capture_order(purchase["paypal_order_id"])
    record_capture(purchase, result["capture_id"], result.get("status", ""))
    return load_purchase(purchase["id"])


def finish_instant(purchase_id: str, allow_created: bool = False) -> dict:
    open_statuses = ("captured", "error", "created") if allow_created else ("captured", "error")
    with purchase_lock(purchase_id):
        purchase = load_purchase(purchase_id)
        if purchase["mode"] != "instant" or purchase["status"] not in open_statuses:
            return purchase
        try:
            purchase = capture_order_once(purchase)
            if not purchase["paypal_payout_batch_id"]:
                pay_seller(purchase)
        except Exception as err:
            update_purchase(purchase_id, status="error", error=error_message(err))
        return load_purchase(purchase_id)
