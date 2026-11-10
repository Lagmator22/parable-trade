from parable import ledger
from parable.db import execute
from parable.referee_math import SIDES, RefereeError

ETH_SCALE = 10**20


def eth_value(eth_wei: int, price: int) -> int:
    return eth_wei * price // ETH_SCALE


def refuse(run: dict, reason: str, detail: str, side: str, amount_usd: int, bot_reason: str) -> None:
    execute("UPDATE runs SET refusals = refusals + 1 WHERE id = ?", (run["id"],))
    ledger.append("run.refused", f"run:{run['id']}", {
        "reason": reason, "detail": detail, "side": side, "amount_usd": amount_usd, "bot_reason": bot_reason,
    })
    raise RefereeError(reason, detail)


def validate_order(run: dict, rules: dict, side: str, amount_usd: int, price: int, bot_reason: str) -> int:
    if side not in SIDES:
        refuse(run, "BadAmount", f"unknown side {side!r}", str(side), 0, bot_reason)
    if isinstance(amount_usd, bool) or not isinstance(amount_usd, int) or amount_usd <= 0:
        refuse(run, "BadAmount", "amount must be a positive integer", side, 0, bot_reason)
    if amount_usd > rules["max_trade_usd"]:
        refuse(run, "OverTradeLimit", f"limit is {rules['max_trade_usd']}", side, amount_usd, bot_reason)
    if side == "buy" and run["cash_usd"] < amount_usd:
        refuse(run, "InsufficientCash", f"cash is {run['cash_usd']}", side, amount_usd, bot_reason)
    if side == "sell" and eth_value(run["eth_wei"], price) < amount_usd:
        refuse(run, "InsufficientEth", f"eth is worth {eth_value(run['eth_wei'], price)}", side, amount_usd,
               bot_reason)
    return amount_usd


def wei_for(amount_usd: int, price: int, side: str) -> int:
    exact = amount_usd * ETH_SCALE
    return exact // price if side == "buy" else -(-exact // price)


def fill_locked(run: dict, side: str, amount_usd: int, price: int, reason: str) -> dict:
    wei = wei_for(amount_usd, price, side)
    cash_delta, eth_delta = (-amount_usd, wei) if side == "buy" else (amount_usd, -min(wei, run["eth_wei"]))
    cash = run["cash_usd"] + cash_delta
    eth_wei = run["eth_wei"] + eth_delta
    equity_after = cash + eth_value(eth_wei, price)
    peak = max(run["peak_equity_usd"], equity_after)
    execute("UPDATE runs SET cash_usd=?, eth_wei=?, peak_equity_usd=?, trades=trades+1 WHERE id=?",
            (cash, eth_wei, peak, run["id"]))
    entry = ledger.append("run.trade", f"run:{run['id']}", {
        "side": side, "amount_usd": amount_usd, "price": price, "eth_delta_wei": eth_delta,
        "reason": reason, "equity_after": equity_after,
    })
    return {"seq": entry["seq"], "run_id": run["id"], "cash_usd": cash, "eth_wei": eth_wei, **entry["data"]}
