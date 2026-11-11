import logging
import math
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Callable, Protocol

from parable.config import get_settings
from parable.errors import LabError
from parable.lab.consts import INTERVAL_SECONDS, MAX_BARS
from parable.lab.popular import popular_static

log = logging.getLogger("parable.lab.markets")

Bar = list[float]
CACHE_SIZE = 256
FAILURE_TTL_S = 30
SEARCH_TTL_S = 600
DONE_TTL_S = 86_400
BUILTIN = ("binance", "mfapi", "fx", "yahoo", "twelve", "sample", "upload")


@dataclass
class SymbolInfo:
    symbol: str
    name: str
    kind: str
    quote: str
    provider: str
    intervals: list[str]
    live: bool


@dataclass
class Quote:
    symbol: str
    price: float
    t: float
    quote: str
    stale: bool


class MarketDataError(LabError):
    def __init__(self, detail: str, status: int = 502) -> None:
        super().__init__(status, "data_unavailable" if status == 502 else "not_found", detail)


class Provider(Protocol):
    id: str
    kinds: tuple[str, ...]
    intervals: tuple[str, ...]

    def search(self, query: str, kind: str) -> list[SymbolInfo]: ...

    def candles(self, code: str, interval: str, limit: int, start: float | None, end: float | None) -> list[Bar]: ...

    def latest(self, code: str) -> Quote: ...

    def info(self, code: str) -> SymbolInfo | None: ...

    def popular(self, kind: str) -> list[SymbolInfo]: ...


_lock = threading.RLock()
_registry: dict[str, Provider] | None = None
_cache: OrderedDict = OrderedDict()
_last_good: dict[str, Quote] = {}
_clock: Callable[[], float] | None = None


def set_clock(fn: Callable[[], float] | None) -> None:
    global _clock
    _clock = fn


def now() -> float:
    return _clock() if _clock else time.time()


def clear_cache() -> None:
    with _lock:
        _cache.clear()
        _last_good.clear()


def build_registry(offline: bool) -> dict[str, Provider]:
    from parable.lab.providers import binance, fx, mfapi, sample, twelve, upload, yahoo

    found: list[Provider] = [sample.SampleProvider(), upload.UploadProvider()]
    if not offline:
        found = [binance.BinanceProvider(), mfapi.MfapiProvider(), fx.FxProvider(), yahoo.YahooProvider()] + found
        if get_settings().twelve_data_key:
            found.append(twelve.TwelveProvider())
    return {p.id: p for p in found}


def reset_providers(offline: bool | None = None) -> None:
    global _registry
    if offline is None:
        offline = get_settings().markets_offline
    with _lock:
        _registry = build_registry(offline)
        clear_cache()


def registry() -> dict[str, Provider]:
    global _registry
    with _lock:
        if _registry is None:
            reset_providers()
        return _registry


def register_provider(provider: Provider) -> None:
    registry()[provider.id] = provider


def unregister_provider(provider_id: str) -> None:
    registry().pop(provider_id, None)


def get_provider(provider_id: str) -> Provider:
    found = registry().get(provider_id)
    if found is None:
        raise MarketDataError(f"unknown market source {provider_id}", 404)
    return found


def split_symbol(symbol: str) -> tuple[Provider, str]:
    provider_id, sep, code = str(symbol).partition(":")
    if not sep or not code:
        raise MarketDataError("symbols look like provider:CODE", 404)
    return get_provider(provider_id), code


def cached(key: tuple, ttl: float | Callable, load: Callable):
    with _lock:
        hit = _cache.get(key)
        if hit and hit[0] > now():
            _cache.move_to_end(key)
            if isinstance(hit[1], Exception):
                raise hit[1]
            return hit[1]
    try:
        value = load()
    except MarketDataError as err:
        store(key, FAILURE_TTL_S, err)
        raise
    store(key, ttl(value) if callable(ttl) else ttl, value)
    return value


def store(key: tuple, ttl: float, value) -> None:
    with _lock:
        _cache[key] = (now() + ttl, value)
        _cache.move_to_end(key)
        while len(_cache) > CACHE_SIZE:
            _cache.popitem(last=False)


def kinds_match(provider: Provider, kind: str) -> bool:
    return kind == "all" or kind in provider.kinds


def search(query: str, kind: str = "all") -> list[SymbolInfo]:
    query = (query or "").strip()
    if not query:
        return popular(kind)
    found: list[SymbolInfo] = []
    for provider in list(registry().values()):
        if not kinds_match(provider, kind):
            continue
        try:
            found += cached(("search", provider.id, query.lower(), kind), SEARCH_TTL_S,
                            lambda p=provider: p.search(query, kind))
        except MarketDataError as err:
            log.info("search skipped %s: %s", provider.id, err.detail)
    return found


def popular(kind: str) -> list[SymbolInfo]:
    reg = registry()
    found = popular_static(kind, "twelve" if "twelve" in reg and "yahoo" not in reg else "yahoo")
    for provider in reg.values():
        if (provider.id not in BUILTIN or provider.id == "sample") and kinds_match(provider, kind):
            found += [i for i in provider.popular(kind) if i.symbol not in {x.symbol for x in found}]
    return found


def symbol_info(symbol: str) -> SymbolInfo:
    provider, code = split_symbol(symbol)
    found = cached(("info", symbol), SEARCH_TTL_S, lambda: provider.info(code))
    if found is None:
        raise MarketDataError(f"unknown symbol {symbol}", 404)
    return found


def quote_currency(symbol: str) -> str:
    return symbol_info(symbol).quote


def intervals_for(symbol: str) -> list[str]:
    return list(symbol_info(symbol).intervals)


def source_kind(symbol: str) -> str:
    head = str(symbol).partition(":")[0]
    return {"sample": "sample", "upload": "creator"}.get(head, "market")


def clean(bars: list[Bar], start: float | None, end: float | None, limit: int) -> list[Bar]:
    out: list[Bar] = []
    last = -math.inf
    for raw in bars:
        try:
            t, o, h, low, c, v = (float(x) for x in raw[:6])
        except (TypeError, ValueError):
            continue
        if not all(math.isfinite(x) for x in (t, o, h, low, c, v)) or t <= last:
            continue
        if h < max(o, c) or low > min(o, c):
            continue
        last = t
        out.append([t, o, h, low, c, v])
    out = [b for b in out if (start is None or b[0] >= start) and (end is None or b[0] < end)]
    return out[:limit] if start is not None and end is None else out[-limit:]


def candles(symbol: str, interval: str, limit: int = 500, start: float | None = None,
            end: float | None = None) -> list[Bar]:
    if interval not in INTERVAL_SECONDS:
        raise LabError(400, "bad_request", f"unknown interval {interval}")
    if not 1 <= int(limit) <= MAX_BARS:
        raise LabError(400, "bad_request", f"limit must be 1..{MAX_BARS}")
    limit = int(limit)
    provider, code = split_symbol(symbol)
    seconds = INTERVAL_SECONDS[interval]
    settled = end is not None and end < now() - 2 * seconds
    ttl = DONE_TTL_S if settled else min(60.0, max(2.0, seconds / 2))
    bars = cached(("candles", symbol, interval, limit, start, end), ttl,
                  lambda: clean(provider.candles(code, interval, limit, start, end), start, end, limit))
    return [list(b) for b in bars]


def closed_candles(symbol: str, interval: str, limit: int = 500, start: float | None = None,
                   end: float | None = None) -> list[Bar]:
    seconds = INTERVAL_SECONDS[interval] if interval in INTERVAL_SECONDS else 0
    cutoff = now()
    return [bar for bar in candles(symbol, interval, limit, start, end) if bar[0] + seconds <= cutoff]


def latest(symbol: str, cached_only: bool = False) -> Quote | None:
    provider, code = split_symbol(symbol)
    ttl = 5 if provider.id == "binance" else 60
    key = ("latest", symbol)
    if cached_only:
        with _lock:
            hit = _cache.get(key)
            if hit and hit[0] > now() and isinstance(hit[1], Quote):
                return hit[1]
            old = _last_good.get(symbol)
        return Quote(old.symbol, old.price, old.t, old.quote, True) if old else None
    try:
        quote = cached(key, ttl, lambda: provider.latest(code))
    except MarketDataError:
        with _lock:
            old = _last_good.get(symbol)
        if old is None:
            raise
        return Quote(old.symbol, old.price, old.t, old.quote, True)
    with _lock:
        _last_good[symbol] = quote
    return quote
