from parable import ledger
from parable.db import execute
from parable.referee_math import RefereeError, Refusal, holdings_value


def refuse_order(run: dict, refusal: Refusal, side: str, amount: object, reason: str) -> None:
    execute("UPDATE runs SET refusals = refusals + 1 WHERE id = ?", (run["id"],))
    ledger.append("run.refused", f"run:{run['id']}", {
        "reason": refusal.reason, "detail": refusal.detail, "side": str(side),
        "amount": amount if isinstance(amount, int) else 0, "bot_reason": reason,
    })
    raise RefereeError(refusal.reason, refusal.detail)


def apply_fill(run: dict, side: str, plan: dict, price: int, reason: str) -> dict:
    cash = run["cash_usd"] + plan["cash_delta"]
    units = run["units"] + plan["units_delta"]
    entry, high = (0, 0) if units <= 0 else (run["entry_price"], run["high_water"])
    if units > 0 and run["units"] == 0:
        entry = high = plan["price"]
    equity_after = cash + holdings_value(units, price)
    peak = max(run["peak_equity_usd"], equity_after)
    execute("UPDATE runs SET cash_usd=?, units=?, entry_price=?, high_water=?, peak_equity_usd=?,"
            " trades=trades+1 WHERE id=?", (cash, units, entry, high, peak, run["id"]))
    logged = ledger.append("run.trade", f"run:{run['id']}", {
        "side": side, "amount": plan["amount"], "price": plan["price"], "units_delta": plan["units_delta"],
        "fee": plan["fee"], "reason": reason, "equity_after": equity_after,
    })
    return {"seq": logged["seq"], "run_id": run["id"], "cash": cash, "units": units, **logged["data"]}
