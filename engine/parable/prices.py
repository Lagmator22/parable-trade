import inspect
import logging
import random
import threading
from decimal import Decimal
from typing import Callable

from parable.config import get_settings

log = logging.getLogger("parable.prices")

PRICE_DECIMALS = 10**8
SIM_START = 3000 * PRICE_DECIMALS
SIM_MAX_STEP_BPS = 30
SIM_PULL_DIVISOR = 20
SIM_SEED = 1337


def to_price(amount: str | float | int) -> int:
    return int(Decimal(str(amount)) * PRICE_DECIMALS)


class PriceState:
    def __init__(self) -> None:
        self.override: Callable[..., int] | None = None
        self.override_arity = 0
        self.sim_price = SIM_START
        self.rng = random.Random(SIM_SEED)


_state = PriceState()
_lock = threading.RLock()


def sim_step() -> int:
    pull_bps = (SIM_START - _state.sim_price) * 10_000 // SIM_START // SIM_PULL_DIVISOR
    step_bps = _state.rng.randint(-SIM_MAX_STEP_BPS, SIM_MAX_STEP_BPS) + pull_bps
    step_bps = max(-SIM_MAX_STEP_BPS, min(SIM_MAX_STEP_BPS, step_bps))
    _state.sim_price = _state.sim_price * (10_000 + step_bps) // 10_000
    return _state.sim_price


def arity_of(source: Callable[..., int]) -> int:
    try:
        params = inspect.signature(source).parameters.values()
    except (TypeError, ValueError):
        return 0
    return sum(p.default is p.empty and p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD) for p in params)


def call_override(source: Callable[..., int], symbol: str) -> int:
    return int(source(symbol)) if _state.override_arity else int(source())


def set_price_source(source: Callable[..., int] | None) -> None:
    global _state
    with _lock:
        _state = PriceState()
        _state.override = source
        _state.override_arity = arity_of(source) if source is not None else 0


def to_scaled(value: float) -> int:
    scaled = to_price(value)
    if scaled <= 0:
        raise ValueError("price must be positive")
    return scaled


def sim_for_symbol() -> int:
    with _lock:
        return sim_step()


def price_for(symbol: str) -> int:
    from parable.lab import markets

    override = _state.override
    if override is not None:
        return call_override(override, symbol)
    settings = get_settings()
    if settings.price_source == "sim":
        if settings.markets_offline:
            try:
                return to_scaled(markets.latest(symbol).price)
            except Exception:
                pass
        return sim_for_symbol()
    return to_scaled(markets.latest(symbol).price)


def cached_price(symbol: str) -> int | None:
    override = _state.override
    if override is not None:
        return call_override(override, symbol)
    from parable.lab import markets

    try:
        found = markets.latest(symbol, cached_only=True)
        return to_scaled(found.price) if found is not None else None
    except Exception:
        return None
