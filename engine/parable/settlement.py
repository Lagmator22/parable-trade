import json
import logging
import secrets
import threading
import time

from parable import analyst, ledger, referee
from parable.db import DB_LOCK, execute, one, rows
from parable.errors import MarketError
from parable.listings import listing_row
from parable.paypal import PayPalError, get_paypal

log = logging.getLogger("parable.settlement")

LIVE_STATUSES = ("authorized", "probation")
UNFINISHED_STATUSES = ("authorized", "probation", "passed", "failed")
ERROR_LIMIT = 300
MIN_EXPLANATION = 20
MAX_EXPLANATION = 300
CONTRADICTIONS = {True: ("voided", "never charged"), False: ("captured", "paid out", "paid to")}

_locks: dict[str, threading.RLock] = {}
_locks_guard = threading.Lock()


def purchase_lock(purchase_id: str) -> threading.RLock:
    with _locks_guard:
        return _locks.setdefault(purchase_id, threading.RLock())


def load_purchase(purchase_id: str) -> dict:
    row = one("SELECT * FROM purchases WHERE id = ?", (purchase_id,))
    if row is None:
        raise MarketError("purchase not found", 404)
    return row


def update_purchase(purchase_id: str, **fields) -> None:
    fields["updated_at"] = int(time.time())
    assignments = ", ".join(f"{column} = ?" for column in fields)
    execute(f"UPDATE purchases SET {assignments} WHERE id = ?", (*fields.values(), purchase_id))


def percent(bps: int) -> str:
    return f"{bps / 100:+.2f}%"


def duration(seconds: int) -> str:
    if seconds < 120:
        return f"{seconds} seconds"
    if seconds < 7200:
        return f"{seconds // 60} minutes"
    return f"{seconds / 3600:.1f} hours"


def build_verdict(run: dict, min_return_bps: int) -> dict:
    return_bps = referee.return_bps(run["start_cash_usd"], run["final_equity_usd"])
    return {
        "passed": run["cause"] == "expired" and return_bps >= min_return_bps,
        "cause": run["cause"],
        "return_bps": return_bps,
        "min_return_bps": min_return_bps,
        "lifetime_s": run["lifetime_s"],
        "trades": run["trades"],
        "refusals": run["refusals"],
    }


def template_explanation(verdict: dict, probation_s: int) -> str:
    result, floor = percent(verdict["return_bps"]), percent(verdict["min_return_bps"])
    if verdict["passed"]:
        return (f"The bot survived the full {duration(probation_s)} probation and returned {result}, meeting the "
                f"promised minimum of {floor}, so the payment was captured.")
    if verdict["cause"] == "loss_limit":
        return (f"The bot hit its loss limit after {duration(verdict['lifetime_s'])} with a return of {result}, so "
                "the payment was voided and the buyer was never charged.")
    if verdict["cause"] == "stopped":
        return (f"The run was stopped after {duration(verdict['lifetime_s'])}, before the probation finished, so the "
                "payment was voided and the buyer was never charged.")
    return (f"The bot survived the probation but returned {result}, below the promised minimum of {floor}, so the "
            "payment was voided and the buyer was never charged.")


def explanation_prompt(verdict: dict, listing: dict) -> str:
    facts = {
        "bot": listing["title"],
        "outcome": "passed" if verdict["passed"] else "failed",
        "ended_because": verdict["cause"],
        "return": percent(verdict["return_bps"]),
        "promised_minimum_return": percent(verdict["min_return_bps"]),
        "probation_length": duration(listing["probation_s"]),
        "lived_for": duration(verdict["lifetime_s"]),
        "trades": verdict["trades"],
        "refused_trades": verdict["refusals"],
    }
    return (
        "You explain the result of a paper-trading probation for an AI trading bot. The payment is captured only "
        "when the bot survives and meets its promised minimum return, otherwise it is voided. The decision is "
        "already made; never question or change it and use only the numbers given.\n"
        f"Facts: {json.dumps(facts)}\n"
        'Reply with JSON only: {"explanation": "<one plain-English sentence, at most 40 words>"}'
    )


def accept_explanation(answer: dict | None, passed: bool) -> str | None:
    text = answer.get("explanation") if answer else None
    if not isinstance(text, str):
        return None
    text = " ".join(text.split())
    lowered = text.lower()
    if not MIN_EXPLANATION <= len(text) <= MAX_EXPLANATION or "\n" in text:
        return None
    return None if any(word in lowered for word in CONTRADICTIONS[passed]) else text


def explain(verdict: dict, listing: dict) -> str:
    answer = analyst.ask(explanation_prompt(verdict, listing))
    return accept_explanation(answer, verdict["passed"]) or template_explanation(verdict, listing["probation_s"])


def record_verdict(purchase: dict, run: dict) -> None:
    listing = listing_row(purchase["listing_id"])
    verdict = build_verdict(run, listing["min_return_bps"])
    verdict["explanation"] = explain(verdict, listing)
    status = "passed" if verdict["passed"] else "failed"
    with DB_LOCK:
        update_purchase(purchase["id"], status=status, run_id=run["id"],
                        verdict_json=json.dumps(verdict, sort_keys=True))
        ledger.append(f"purchase.{status}", f"purchase:{purchase['id']}", {"run_id": run["id"], **verdict})


def capture(purchase: dict) -> None:
    result = get_paypal().capture_authorization(
        purchase["paypal_authorization_id"], purchase["amount_cents"], purchase["id"], final=True)
    key = purchase["license_key"] or "pk_" + secrets.token_urlsafe(18)
    with DB_LOCK:
        update_purchase(purchase["id"], status="captured", paypal_capture_id=result["capture_id"],
                        license_key=key, error=None)
        ledger.append("payment.captured", f"purchase:{purchase['id']}", {
            "capture_id": result["capture_id"], "amount_cents": purchase["amount_cents"],
            "fee_cents": purchase["fee_cents"], "status": result.get("status", "")})


def pay_seller(purchase: dict) -> None:
    listing = listing_row(purchase["listing_id"])
    seller = one("SELECT email FROM sellers WHERE id = ?", (listing["seller_id"],)) or {}
    payout_cents = purchase["amount_cents"] - purchase["fee_cents"]
    result = get_paypal().create_payout(
        f"{purchase['id']}-payout", seller.get("email") or "", payout_cents, f"Parable sale: {listing['title']}"[:200])
    with DB_LOCK:
        update_purchase(purchase["id"], status="paid_out", paypal_payout_batch_id=result["payout_batch_id"],
                        payout_status=result["batch_status"], error=None)
        ledger.append("payout.sent", f"purchase:{purchase['id']}", {
            "payout_batch_id": result["payout_batch_id"], "batch_status": result["batch_status"],
            "amount_cents": payout_cents, "fee_cents": purchase["fee_cents"]})


def void_hold(purchase: dict) -> None:
    if purchase["status"] == "voided":
        return
    get_paypal().void_authorization(purchase["paypal_authorization_id"])
    with DB_LOCK:
        update_purchase(purchase["id"], status="voided", error=None)
        ledger.append("payment.voided", f"purchase:{purchase['id']}", {
            "authorization_id": purchase["paypal_authorization_id"], "amount_cents": purchase["amount_cents"]})


def capture_and_pay(purchase: dict) -> None:
    if not purchase["paypal_capture_id"]:
        capture(purchase)
        purchase = load_purchase(purchase["id"])
    if not purchase["paypal_payout_batch_id"]:
        pay_seller(purchase)


def error_message(err: Exception) -> str:
    if isinstance(err, PayPalError):
        return f"{err.name}: {err.detail}"[:ERROR_LIMIT]
    log.exception("settlement failed")
    return f"internal error: {type(err).__name__}"


def carry_out(purchase_id: str) -> dict:
    with purchase_lock(purchase_id):
        purchase = load_purchase(purchase_id)
        passed = json.loads(purchase["verdict_json"])["passed"]
        try:
            if passed:
                capture_and_pay(purchase)
            else:
                void_hold(purchase)
        except Exception as err:
            update_purchase(purchase_id, status="error", error=error_message(err))
        return load_purchase(purchase_id)


def resume_status(purchase: dict, verdict: dict) -> str:
    if not verdict["passed"]:
        return "failed"
    return "captured" if purchase["paypal_capture_id"] else "passed"


def resume(purchase: dict) -> dict:
    with purchase_lock(purchase["id"]):
        verdict = json.loads(purchase["verdict_json"])
        update_purchase(purchase["id"], status=resume_status(purchase, verdict), error=None)
        return carry_out(purchase["id"])


def settle_run(run: dict) -> None:
    purchase_id = run.get("purchase_id")
    if not purchase_id:
        return
    with purchase_lock(purchase_id):
        purchase = load_purchase(purchase_id)
        if purchase["status"] not in LIVE_STATUSES:
            return
        record_verdict(purchase, run)
        carry_out(purchase_id)


def on_run_ended(run: dict) -> None:
    if not run.get("purchase_id"):
        return
    threading.Thread(target=settle_safely, args=(run,), daemon=True, name=f"settle-{run['purchase_id']}").start()


def settle_safely(run: dict) -> None:
    try:
        settle_run(run)
    except Exception:
        log.exception("settling purchase %s failed", run.get("purchase_id"))


def settle_pending() -> int:
    handled = 0
    placeholders = ",".join("?" for _ in UNFINISHED_STATUSES)
    for purchase in rows(f"SELECT * FROM purchases WHERE status IN ({placeholders})", UNFINISHED_STATUSES):
        if purchase["status"] in LIVE_STATUSES:
            handled += settle_dead_run(purchase)
        else:
            carry_out(purchase["id"])
            handled += 1
    return handled


def settle_dead_run(purchase: dict) -> int:
    run = one("SELECT id, status FROM runs WHERE purchase_id = ?", (purchase["id"],))
    if run is None or run["status"] != "dead":
        return 0
    settle_run(referee.get_run(run["id"]))
    return 1
