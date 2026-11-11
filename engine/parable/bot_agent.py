import logging
import re
import time
from threading import Event

from parable import prices, referee
from parable.models import RunRules
from parable.referee_math import buy_amount, sell_amount

log = logging.getLogger("parable.bot")

PRICE_SCALE = 1e8


def redact(err: Exception) -> str:
    return f"{type(err).__name__}: " + re.sub(r"https?://\S+", "<url>", str(err))[:300]


def position_of(run: dict, entry_t: float):
    from parable.lab.signals import Position

    if run["units"] <= 0:
        return None
    return Position(entry_price=run["entry_price"] / PRICE_SCALE, entry_t=entry_t,
                    high_water=max(run["high_water"], run["entry_price"]) / PRICE_SCALE)


def sell_all(run_id: int, run: dict, price: int, spec, reason: str) -> bool:
    amount = sell_amount(run["units"], price)
    try:
        referee.place_order(run_id, "sell", amount, reason, fee_bps=spec.fee_bps, slippage_bps=spec.slippage_bps)
    except referee.RefereeError:
        return False
    return True


def buy_in(run_id: int, run: dict, rules: RunRules, spec, reason: str) -> bool:
    amount = buy_amount(run["cash_usd"], rules.max_trade, spec.size_pct, spec.fee_bps)
    if amount <= 0:
        return False
    try:
        referee.place_order(run_id, "buy", amount, reason, fee_bps=spec.fee_bps, slippage_bps=spec.slippage_bps)
    except referee.RefereeError:
        return False
    return True


def check_stops(run_id: int, run: dict, spec, price: int, state: dict) -> dict:
    from parable.lab import signals

    position = position_of(run, state["entry_t"])
    if position is None:
        return run
    level = price / PRICE_SCALE
    hit = signals.stop_reason(spec, position, level, level, level)
    if hit is not None and sell_all(run_id, run, price, spec, hit[0]):
        return referee.load(run_id)
    referee.mark(run_id, price=price)
    return referee.load(run_id)


def act_on_bar(run_id: int, run: dict, rules: RunRules, spec, closed: list, state: dict) -> None:
    from parable.lab import signals

    decision = signals.decide(spec, closed, position_of(run, state["entry_t"]))
    if decision.action == "buy" and run["units"] <= 0:
        if buy_in(run_id, run, rules, spec, decision.reason):
            state["entry_t"] = time.time()
    elif decision.action == "sell" and run["units"] > 0:
        sell_all(run_id, run, prices.price_for(rules.symbol), spec, decision.reason)


def new_closed_bars(rules: RunRules, spec, last_bar_t: int) -> list | None:
    from parable.lab import markets, signals
    from parable.lab.spec import required_bars

    bars = markets.candles(rules.symbol, rules.interval, required_bars(spec))
    closed = signals.closed_bars(bars, rules.interval, time.time())
    return closed if closed and closed[-1][0] > last_bar_t else None


def count_new_bars(closed: list, last_bar_t: int) -> int:
    if not last_bar_t:
        return 1
    return max(1, sum(1 for bar in closed if bar[0] > last_bar_t))


def tick(run_id: int, rules: RunRules, spec, state: dict) -> bool:
    if referee.load(run_id)["status"] != "alive":
        return False
    price = prices.price_for(rules.symbol)
    referee.record_point(run_id, price)
    if referee.check(run_id) is not None:
        return False
    run = check_stops(run_id, referee.load(run_id), spec, price, state)
    closed = new_closed_bars(rules, spec, run["last_bar_t"])
    if closed is not None and run["status"] == "alive":
        act_on_bar(run_id, run, rules, spec, closed, state)
        referee.mark(run_id, last_bar_t=int(closed[-1][0]), new_bars=count_new_bars(closed, run["last_bar_t"]))
    return True


def run_agent(run_id: int, stop_event: Event, interval_s: float) -> None:
    from parable.lab.spec import load_spec

    run = referee.load(run_id)
    rules = RunRules.model_validate_json(run["rules_json"])
    spec = load_spec(rules.version_id)
    state = {"entry_t": float(run["started_at"])}
    while not stop_event.is_set():
        try:
            if not tick(run_id, rules, spec, state):
                return
        except referee.RunNotFound:
            return
        except Exception as err:
            log.warning("agent turn for run %s skipped: %s", run_id, redact(err))
        stop_event.wait(interval_s)
