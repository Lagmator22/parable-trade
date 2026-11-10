import math
import random
import time

import pytest

from parable.lab import markets
from parable.lab.markets import MarketDataError, Quote, SymbolInfo

SYNTHETIC = True


def make_bars(n: int, start_t: float = 1_700_000_000, interval_s: int = 3600, seed: int = 1,
              drift: float = 0.0005, vol: float = 0.01) -> list[list[float]]:
    rng = random.Random(seed)
    price = 100.0
    out = []
    for i in range(n):
        open_ = price
        close = max(0.01, open_ * (1 + drift + vol * rng.gauss(0, 1)))
        high = max(open_, close) * (1 + abs(rng.gauss(0, vol / 3)))
        low = min(open_, close) * (1 - abs(rng.gauss(0, vol / 3)))
        out.append([float(start_t + i * interval_s), round(open_, 6), round(high, 6), round(low, 6),
                    round(close, 6), round(1000 + 500 * rng.random(), 6)])
        price = close
    return out


class FakeProvider:
    def __init__(self, provider_id: str = "fake", kinds: tuple[str, ...] = ("crypto",), quote: str = "USDT",
                 intervals: tuple[str, ...] = ("1m", "1h", "1d"), bars_by_code: dict | None = None,
                 price: float = 100.0) -> None:
        self.id = provider_id
        self.kinds = kinds
        self.quote = quote
        self.intervals = intervals
        self.bars_by_code = bars_by_code if bars_by_code is not None else {"BTCUSDT": make_bars(500)}
        self.price = price
        self.calls = {"search": 0, "candles": 0, "latest": 0, "info": 0}
        self.fail = False

    def make_info(self, code: str) -> SymbolInfo:
        return SymbolInfo(f"{self.id}:{code}", code, self.kinds[0], self.quote, self.id, list(self.intervals), True)

    def check(self) -> None:
        if self.fail:
            raise MarketDataError("fake outage")

    def search(self, query: str, kind: str) -> list[SymbolInfo]:
        self.calls["search"] += 1
        self.check()
        return [self.make_info(c) for c in self.bars_by_code if query.upper() in c]

    def candles(self, code: str, interval: str, limit: int, start: float | None, end: float | None):
        self.calls["candles"] += 1
        self.check()
        if code not in self.bars_by_code:
            raise MarketDataError("unknown fake symbol", 404)
        if interval not in self.intervals:
            raise MarketDataError("unsupported interval", 404)
        return [list(b) for b in self.bars_by_code[code]]

    def latest(self, code: str) -> Quote:
        self.calls["latest"] += 1
        self.check()
        if code not in self.bars_by_code:
            raise MarketDataError("unknown fake symbol", 404)
        return Quote(f"{self.id}:{code}", self.price, time.time(), self.quote, False)

    def info(self, code: str) -> SymbolInfo | None:
        self.calls["info"] += 1
        return self.make_info(code) if code in self.bars_by_code else None

    def popular(self, kind: str) -> list[SymbolInfo]:
        return [self.make_info(c) for c in self.bars_by_code] if kind in self.kinds or kind == "all" else []


def install_fake(**kw) -> FakeProvider:
    markets.reset_providers(offline=True)
    fake = FakeProvider(**kw)
    markets.register_provider(fake)
    return fake


@pytest.fixture
def fake_market():
    fake = install_fake()
    yield fake
    markets.set_clock(None)
    markets.reset_providers(offline=True)


def finite(bars) -> bool:
    return all(math.isfinite(x) for bar in bars for x in bar)
