import logging
import random
import threading
import time
from collections import deque
from decimal import Decimal, InvalidOperation
from typing import Callable

import httpx

from parable.config import get_settings

log = logging.getLogger("parable.prices")

PRICE_DECIMALS = 10**8
CACHE_TTL_S = 2
FETCH_TIMEOUT_S = 3
SIM_START = 3000 * PRICE_DECIMALS
SIM_MAX_STEP_BPS = 30
SIM_PULL_DIVISOR = 20
SIM_SEED = 1337
HISTORY_LIMIT = 720
SAMPLE_EVERY_S = 5


def to_price(amount: str | float | int) -> int:
    return int(Decimal(str(amount)) * PRICE_DECIMALS)


def read_coinbase(payload: dict) -> int:
    return to_price(payload["data"]["amount"])


def read_kraken(payload: dict) -> int:
    ticker = next(iter(payload["result"].values()))
    return to_price(ticker["c"][0])


def read_binance(payload: dict) -> int:
    return to_price(payload["price"])


LIVE_SOURCES = (
    ("https://api.coinbase.com/v2/prices/ETH-USD/spot", read_coinbase),
    ("https://api.kraken.com/0/public/Ticker?pair=ETHUSD", read_kraken),
    ("https://api.binance.com/api/v3/ticker/price?symbol=ETHUSDT", read_binance),
)
READ_ERRORS = (httpx.HTTPError, KeyError, IndexError, StopIteration, TypeError, ValueError, InvalidOperation)


class PriceState:
    def __init__(self) -> None:
        self.override: Callable[[], int] | None = None
        self.cached: tuple[float, int] | None = None
        self.last_good: int | None = None
        self.sim_price = SIM_START
        self.rng = random.Random(SIM_SEED)
        self.samples: deque[tuple[int, int]] = deque(maxlen=HISTORY_LIMIT)


_state = PriceState()
_lock = threading.RLock()
_sampler: threading.Thread | None = None
_sampler_stop = threading.Event()


def fetch_live() -> int | None:
    for url, read in LIVE_SOURCES:
        try:
            response = httpx.get(url, timeout=FETCH_TIMEOUT_S)
            response.raise_for_status()
            value = read(response.json())
        except READ_ERRORS:
            continue
        if value > 0:
            return value
    return None


def sim_step() -> int:
    pull_bps = (SIM_START - _state.sim_price) * 10_000 // SIM_START // SIM_PULL_DIVISOR
    step_bps = _state.rng.randint(-SIM_MAX_STEP_BPS, SIM_MAX_STEP_BPS) + pull_bps
    step_bps = max(-SIM_MAX_STEP_BPS, min(SIM_MAX_STEP_BPS, step_bps))
    _state.sim_price = _state.sim_price * (10_000 + step_bps) // 10_000
    return _state.sim_price


def fetch_fresh() -> int:
    if get_settings().price_source == "sim":
        return sim_step()
    live = fetch_live()
    if live is not None:
        _state.last_good = live
        return live
    if _state.last_good is not None:
        return _state.last_good
    return sim_step()


def price() -> int:
    override = _state.override
    if override is not None:
        return int(override())
    with _lock:
        now = time.monotonic()
        if _state.cached and now - _state.cached[0] < CACHE_TTL_S:
            return _state.cached[1]
        value = fetch_fresh()
        _state.cached = (now, value)
        return value


def set_price_source(source: Callable[[], int] | None) -> None:
    global _state
    with _lock:
        _state = PriceState()
        _state.override = source


def record_sample() -> tuple[int, int]:
    sample = (int(time.time()), price())
    with _lock:
        _state.samples.append(sample)
    return sample


def history(n: int = 60) -> list[tuple[int, int]]:
    with _lock:
        return list(_state.samples)[-n:] if n > 0 else []


def sampler_loop(every_s: float, stop: threading.Event) -> None:
    while not stop.is_set():
        try:
            record_sample()
        except Exception:
            log.warning("price sample failed", exc_info=True)
        stop.wait(every_s)


def start_sampler(every_s: float = SAMPLE_EVERY_S) -> None:
    global _sampler, _sampler_stop
    with _lock:
        if _sampler is not None and _sampler.is_alive():
            return
        _sampler_stop = threading.Event()
        _sampler = threading.Thread(target=sampler_loop, args=(every_s, _sampler_stop), daemon=True,
                                    name="price-sampler")
        _sampler.start()


def stop_sampler() -> None:
    global _sampler
    _sampler_stop.set()
    thread, _sampler = _sampler, None
    if thread is not None:
        thread.join(timeout=2)
