import json
import logging
import time
from typing import Callable, Literal

from parable import ledger, prices
from parable.db import DB_LOCK, execute, one, rows
from parable.models import BotRules, RunRules, fingerprint
from parable.referee_hooks import _end_hooks, add_end_hook, announce_ended, clear_end_hooks, remove_end_hook
from parable.referee_legacy import eth_value, fill_locked, refuse, validate_order, wei_for
from parable.referee_math import (BPS, SIDES, RefereeError, Refusal, check_order, drawdown_bps, holdings_value,
                                  plan_fill, return_bps)
from parable.referee_orders import apply_fill, refuse_order
from parable.referee_points import insert_point, last_price, points
from parable.referee_records import probation_passed, seller_record

log = logging.getLogger("parable.referee")

PURPOSES = ("practice", "probation", "track")
END_CAUSES = ("expired", "loss_limit", "stopped")
REASON_LIMIT = 300

class RunNotFound(LookupError):
    pass


def now() -> int:
    return int(time.time())


def load(run_id: int) -> dict:
    run = one("SELECT * FROM runs WHERE id = ?", (run_id,))
    if run is None:
        raise RunNotFound(f"run {run_id} not found")
    return run


def equity_at(run: dict, price: int) -> int:
    if run["status"] != "alive":
        return run["final_equity_usd"]
    if run.get("version_id"):
        return run["cash_usd"] + holdings_value(run["units"], price)
    return run["cash_usd"] + eth_value(run["eth_wei"], price)


def view_price(run: dict) -> int:
    cached = prices.cached_price(run["symbol"])
    if cached is not None:
        return cached
    seen = last_price(run["id"])
    if seen is not None:
        return seen
    return run["entry_price"] or 0


def mark_price(run: dict) -> int:
    if not run.get("version_id"):
        return prices.price()
    try:
        return prices.price_for(run["symbol"])
    except Exception:
        return view_price(run)


def loss_limit_hit(run: dict, equity: int) -> bool:
    max_loss_bps = json.loads(run["rules_json"])["max_loss_bps"]
    peak = max(run["peak_equity_usd"], equity)
    return (peak - equity) * BPS >= max_loss_bps * peak


def open_run(seller_id: str, rules: BotRules | RunRules, purpose: str, name: str, listing_id: str | None = None,
             purchase_id: str | None = None) -> dict:
    if purpose not in PURPOSES:
        raise ValueError(f"purpose must be one of {PURPOSES}")
    if isinstance(rules, RunRules):
        return open_agent_run(seller_id, rules, purpose, name, listing_id, purchase_id)
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


def open_agent_run(seller_id: str, rules: RunRules, purpose: str, name: str, listing_id: str | None,
                   purchase_id: str | None) -> dict:
    started = now()
    with DB_LOCK:
        run_id = execute(
            "INSERT INTO runs (seller_id, listing_id, purchase_id, purpose, name, rules_json, fingerprint, status,"
            " cash_usd, eth_wei, start_cash_usd, peak_equity_usd, started_at, expires_at, version_id, spec_hash,"
            " symbol, interval, quote, units, entry_price, high_water, last_bar_t)"
            " VALUES (?,?,?,?,?,?,?,'alive',?,0,?,?,?,?,?,?,?,?,?,0,0,0,0)",
            (seller_id, listing_id, purchase_id, purpose, name, rules.model_dump_json(), rules.spec_hash,
             rules.start_cash, rules.start_cash, rules.start_cash, started, started + rules.lease_seconds,
             rules.version_id, rules.spec_hash, rules.symbol, rules.interval, rules.quote),
        )
        ledger.append("run.started", f"run:{run_id}", {
            "seller_id": seller_id, "listing_id": listing_id, "purchase_id": purchase_id, "purpose": purpose,
            "name": name, "rules": rules.model_dump(), "version_id": rules.version_id,
            "spec_hash": rules.spec_hash, "start_cash": rules.start_cash,
            "expires_at": started + rules.lease_seconds,
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
    price = mark_price(load(run_id))
    with DB_LOCK:
        ended = check_locked(run_id, price)
    if ended is not None:
        announce_ended([ended])
    return ended


def stop(run_id: int, cause: str = "stopped") -> dict:
    if cause not in END_CAUSES:
        raise ValueError(f"cause must be one of {END_CAUSES}")
    price = mark_price(load(run_id))
    ended = None
    with DB_LOCK:
        run = load(run_id)
        if run["status"] == "alive":
            ended = finish_locked(run, cause, equity_at(run, price))
    if ended is not None:
        announce_ended([ended])
    return get_run(run_id)


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
    run = load(run_id)
    return equity_at(run, mark_price(run))


def view(run: dict, price: int) -> dict:
    current = equity_at(run, price)
    alive = run["status"] == "alive"
    end = run["ended_at"] if run["ended_at"] else now()
    base = {k: v for k, v in run.items() if k != "rules_json"} if run.get("version_id") else run
    return {
        **base,
        "rules": json.loads(run["rules_json"]),
        "equity_usd": current,
        "pnl_bps": return_bps(run["start_cash_usd"], current),
        "drawdown_bps": drawdown_bps(max(run["peak_equity_usd"], current), current),
        "seconds_left": max(0, run["expires_at"] - now()) if alive else 0,
        "lifetime_s": end - run["started_at"],
    }


def view_for(run: dict, legacy_price: Callable[[], int]) -> dict:
    return view(run, view_price(run) if run.get("version_id") else legacy_price())


def get_run(run_id: int) -> dict:
    return view_for(load(run_id), prices.price)


def list_runs(seller_id: str | None = None, status: str | None = None, purpose: str | None = None,
              limit: int = 200) -> list[dict]:
    clauses, params = [], []
    for column, value in (("seller_id", seller_id), ("status", status), ("purpose", purpose)):
        if value is not None:
            clauses.append(f"{column} = ?")
            params.append(value)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    found = rows(f"SELECT * FROM runs {where} ORDER BY id DESC LIMIT ?", (*params, limit))
    cache: list[int] = []

    def legacy_price() -> int:
        if not cache:
            cache.append(prices.price())
        return cache[0]

    return [view_for(run, legacy_price) for run in found]


def order_locked(run_id: int, side: str, amount: int, reason: str, price: int, fee_bps: float,
                 slippage_bps: float, ended: list[dict]) -> dict:
    run = load(run_id)
    if run["status"] != "alive":
        raise RefereeError("NotAlive", f"run {run_id} is {run['cause']}")
    closed = check_locked(run_id, price)
    if closed is not None:
        ended.append(closed)
        raise RefereeError("Expired" if closed["cause"] == "expired" else "NotAlive", closed["cause"])
    run, reason = load(run_id), (reason or "")[:REASON_LIMIT]
    try:
        limit = json.loads(run["rules_json"])["max_trade"]
        plan = plan_fill(run, side, check_order(side, amount, limit), price, fee_bps, slippage_bps)
    except Refusal as refusal:
        refuse_order(run, refusal, side, amount, reason)
    return apply_fill(run, side, plan, price, reason)


def place_order(run_id: int, side: Literal["buy", "sell"], amount: int, reason: str, *, fee_bps: float = 0,
                slippage_bps: float = 0) -> dict:
    price = prices.price_for(load(run_id)["symbol"])
    ended: list[dict] = []
    try:
        with DB_LOCK:
            return order_locked(run_id, side, amount, reason, price, fee_bps, slippage_bps, ended)
    finally:
        announce_ended(ended)


def record_point(run_id: int, price: int | None = None) -> None:
    run = load(run_id)
    seen = price if price is not None else view_price(run)
    insert_point(run_id, now(), equity_at(run, seen), seen if seen else None)


def mark(run_id: int, *, last_bar_t: int | None = None, price: int | None = None) -> None:
    if last_bar_t is not None:
        execute("UPDATE runs SET last_bar_t = ? WHERE id = ?", (last_bar_t, run_id))
    if price is not None:
        execute("UPDATE runs SET high_water = ? WHERE id = ? AND units > 0 AND high_water < ?",
                (price, run_id, price))
