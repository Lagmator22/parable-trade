import json
import logging
import time
from typing import Callable

from parable import ledger, prices
from parable.db import DB_LOCK, execute, one, rows
from parable.models import BotRules, fingerprint

log = logging.getLogger("parable.referee")

PURPOSES = ("practice", "probation")
END_CAUSES = ("expired", "loss_limit", "stopped")
SIDES = ("buy", "sell")
ETH_SCALE = 10**20
BPS = 10_000
REASON_LIMIT = 300

_end_hooks: list[Callable[[dict], None]] = []


class RefereeError(Exception):
    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail


class RunNotFound(LookupError):
    pass


def add_end_hook(hook: Callable[[dict], None]) -> None:
    if hook not in _end_hooks:
        _end_hooks.append(hook)


def remove_end_hook(hook: Callable[[dict], None]) -> None:
    if hook in _end_hooks:
        _end_hooks.remove(hook)


def clear_end_hooks() -> None:
    _end_hooks.clear()


def announce_ended(ended: list[dict]) -> None:
    for run in ended:
        final = get_run(run["id"])
        for hook in list(_end_hooks):
            try:
                hook(final)
            except Exception:
                log.exception("end hook failed for run %s", run["id"])


def now() -> int:
    return int(time.time())


def load(run_id: int) -> dict:
    run = one("SELECT * FROM runs WHERE id = ?", (run_id,))
    if run is None:
        raise RunNotFound(f"run {run_id} not found")
    return run


def eth_value(eth_wei: int, price: int) -> int:
    return eth_wei * price // ETH_SCALE


def equity_at(run: dict, price: int) -> int:
    if run["status"] != "alive":
        return run["final_equity_usd"]
    return run["cash_usd"] + eth_value(run["eth_wei"], price)


def return_bps(start_cash: int, final_equity: int) -> int:
    return (final_equity - start_cash) * BPS // start_cash


def drawdown_bps(peak: int, current: int) -> int:
    return max(0, (peak - current) * BPS // peak) if peak > 0 else 0


def loss_limit_hit(run: dict, equity: int) -> bool:
    max_loss_bps = json.loads(run["rules_json"])["max_loss_bps"]
    peak = max(run["peak_equity_usd"], equity)
    return (peak - equity) * BPS >= max_loss_bps * peak


def open_run(seller_id: str, rules: BotRules, purpose: str, name: str, listing_id: str | None = None,
             purchase_id: str | None = None) -> dict:
    if purpose not in PURPOSES:
        raise ValueError(f"purpose must be one of {PURPOSES}")
    started = now()
    code = fingerprint(rules)
    with DB_LOCK:
        run_id = execute(
            "INSERT INTO runs (seller_id, listing_id, purchase_id, purpose, name, rules_json, fingerprint, status,"
            " cash_usd, eth_wei, start_cash_usd, peak_equity_usd, started_at, expires_at)"
            " VALUES (?,?,?,?,?,?,?,'alive',?,0,?,?,?,?)",
            (seller_id, listing_id, purchase_id, purpose, name, rules.model_dump_json(), code,
             rules.start_cash_usd, rules.start_cash_usd, rules.start_cash_usd, started,
             started + rules.lease_seconds),
        )
        ledger.append("run.started", f"run:{run_id}", {
            "seller_id": seller_id, "listing_id": listing_id, "purchase_id": purchase_id, "purpose": purpose,
            "name": name, "rules": rules.model_dump(), "fingerprint": code,
            "start_cash_usd": rules.start_cash_usd, "expires_at": started + rules.lease_seconds,
        })
    return get_run(run_id)


def finish_locked(run: dict, cause: str, equity: int) -> dict:
    ended_at = now()
    peak = max(run["peak_equity_usd"], equity)
    execute(
        "UPDATE runs SET status='dead', cause=?, final_equity_usd=?, peak_equity_usd=?, ended_at=? WHERE id=?",
        (cause, equity, peak, ended_at, run["id"]),
    )
    ledger.append("run.ended", f"run:{run['id']}", {
        "cause": cause, "final_equity_usd": equity, "start_cash_usd": run["start_cash_usd"],
        "return_bps": return_bps(run["start_cash_usd"], equity), "lifetime_s": ended_at - run["started_at"],
        "trades": run["trades"], "refusals": run["refusals"],
    })
    return load(run["id"])


def check_locked(run_id: int, price: int) -> dict | None:
    run = load(run_id)
    if run["status"] != "alive":
        return None
    equity = equity_at(run, price)
    if now() >= run["expires_at"]:
        return finish_locked(run, "expired", equity)
    if loss_limit_hit(run, equity):
        return finish_locked(run, "loss_limit", equity)
    if equity > run["peak_equity_usd"]:
        execute("UPDATE runs SET peak_equity_usd = ? WHERE id = ?", (equity, run_id))
    return None


def check(run_id: int) -> dict | None:
    price = prices.price()
    with DB_LOCK:
        ended = check_locked(run_id, price)
    if ended is not None:
        announce_ended([ended])
    return ended


def stop(run_id: int, cause: str = "stopped") -> dict:
    if cause not in END_CAUSES:
        raise ValueError(f"cause must be one of {END_CAUSES}")
    price = prices.price()
    ended = None
    with DB_LOCK:
        run = load(run_id)
        if run["status"] == "alive":
            ended = finish_locked(run, cause, equity_at(run, price))
    if ended is not None:
        announce_ended([ended])
    return get_run(run_id)


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


def trade_locked(run_id: int, side: str, amount_usd: int, reason: str, price: int, ended: list[dict]) -> dict:
    run = load(run_id)
    if run["status"] != "alive":
        raise RefereeError("NotAlive", f"run {run_id} is {run['cause']}")
    closed = check_locked(run_id, price)
    if closed is not None:
        ended.append(closed)
        raise RefereeError("Expired" if closed["cause"] == "expired" else "NotAlive", closed["cause"])
    rules = json.loads(run["rules_json"])
    reason = (reason or "")[:REASON_LIMIT]
    amount = validate_order(run, rules, side, amount_usd, price, reason)
    return fill_locked(load(run_id), side, amount, price, reason)


def trade(run_id: int, side: str, amount_usd: int, reason: str) -> dict:
    price = prices.price()
    ended: list[dict] = []
    try:
        with DB_LOCK:
            return trade_locked(run_id, side, amount_usd, reason, price, ended)
    finally:
        announce_ended(ended)


def equity(run_id: int) -> int:
    return equity_at(load(run_id), prices.price())


def view(run: dict, price: int) -> dict:
    current = equity_at(run, price)
    alive = run["status"] == "alive"
    end = run["ended_at"] if run["ended_at"] else now()
    return {
        **run,
        "rules": json.loads(run["rules_json"]),
        "equity_usd": current,
        "pnl_bps": return_bps(run["start_cash_usd"], current),
        "drawdown_bps": drawdown_bps(max(run["peak_equity_usd"], current), current),
        "seconds_left": max(0, run["expires_at"] - now()) if alive else 0,
        "lifetime_s": end - run["started_at"],
    }


def get_run(run_id: int) -> dict:
    return view(load(run_id), prices.price())


def list_runs(seller_id: str | None = None, status: str | None = None, purpose: str | None = None,
              limit: int = 200) -> list[dict]:
    clauses, params = [], []
    for column, value in (("seller_id", seller_id), ("status", status), ("purpose", purpose)):
        if value is not None:
            clauses.append(f"{column} = ?")
            params.append(value)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    found = rows(f"SELECT * FROM runs {where} ORDER BY id DESC LIMIT ?", (*params, limit))
    price = prices.price()
    return [view(run, price) for run in found]


def probation_passed(run: dict, thresholds: dict[str, int]) -> bool:
    threshold = thresholds.get(run["listing_id"], 0)
    return run["cause"] == "expired" and return_bps(run["start_cash_usd"], run["final_equity_usd"]) >= threshold


def seller_record(seller_id: str) -> dict:
    found = rows("SELECT * FROM runs WHERE seller_id = ?", (seller_id,))
    ended = [r for r in found if r["status"] == "dead"]
    returns = [return_bps(r["start_cash_usd"], r["final_equity_usd"]) for r in ended]
    survived = [r for r in ended if r["cause"] == "expired"]
    thresholds = {l["id"]: l["min_return_bps"] for l in rows(
        "SELECT id, min_return_bps FROM listings WHERE seller_id = ?", (seller_id,))}
    probations = [r for r in ended if r["purpose"] == "probation"]
    passed = [r for r in probations if probation_passed(r, thresholds)]
    return {
        "runs": len(found),
        "alive": len(found) - len(ended),
        "ended": len(ended),
        "survived": len(survived),
        "loss_limit": sum(r["cause"] == "loss_limit" for r in ended),
        "stopped": sum(r["cause"] == "stopped" for r in ended),
        "survival_rate": len(survived) / len(ended) if ended else 0.0,
        "avg_return_bps": sum(returns) // len(returns) if returns else 0,
        "worst_return_bps": min(returns, default=0),
        "best_return_bps": max(returns, default=0),
        "total_trades": sum(r["trades"] for r in found),
        "total_refusals": sum(r["refusals"] for r in found),
        "practice_runs": sum(r["purpose"] == "practice" for r in found),
        "probation_runs": sum(r["purpose"] == "probation" for r in found),
        "probation_passed": len(passed),
        "probation_failed": len(probations) - len(passed),
    }
