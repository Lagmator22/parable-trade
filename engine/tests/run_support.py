import sys
import types
from dataclasses import dataclass

import pytest

from parable import referee
from parable.db import execute
from parable.lab import markets
from parable.models import RunRules

USD = 1_000_000
PRICE = 3000 * 10**8
SYMBOL = "fake:BTCUSDT"
VERSION = "v_test000001"
SPEC_HASH = "ab" * 32


class CountingProvider:
    id = "fake"
    kinds = ("crypto",)
    intervals = ("1m", "1h")

    def __init__(self, price: float = 3000.0) -> None:
        self.calls = 0
        self.price = price
        self.bars: list[list[float]] = []

    def info(self, code: str):
        self.calls += 1
        return markets.SymbolInfo(f"fake:{code}", code, "crypto", "USDT", "fake", list(self.intervals), True)

    def latest(self, code: str):
        self.calls += 1
        return markets.Quote(f"fake:{code}", self.price, 0.0, "USDT", False)

    def candles(self, code, interval, limit, start, end):
        self.calls += 1
        return [list(b) for b in self.bars]

    def search(self, query, kind):
        self.calls += 1
        return []

    def popular(self, kind):
        self.calls += 1
        return []


@pytest.fixture
def feed():
    markets.reset_providers(offline=True)
    provider = CountingProvider()
    markets.register_provider(provider)
    yield provider
    markets.reset_providers(offline=True)


def agent_rules(**overrides) -> RunRules:
    base = {"version_id": VERSION, "spec_hash": SPEC_HASH, "symbol": SYMBOL, "interval": "1h", "quote": "USDT",
            "start_cash": 1000 * USD, "max_trade": 1000 * USD, "max_loss_bps": 2000, "lease_seconds": 300}
    return RunRules(**{**base, **overrides})


def agent_run(purpose: str = "practice", **overrides) -> dict:
    return referee.open_run("s_test", agent_rules(**overrides), purpose, "Agent run")


def insert_version(version_id: str = VERSION, spec_hash: str = SPEC_HASH) -> None:
    column = "spec_" + "json"
    execute(f"INSERT INTO agent_versions (id, agent_id, n, name, {column}, spec_hash) VALUES (?,?,?,?,?,?)",
            (version_id, "a_test000001", 1, "v1", "{}", spec_hash))


@dataclass
class FakePosition:
    entry_price: float
    entry_t: float
    high_water: float


@dataclass
class FakeDecision:
    action: str
    reason: str = "fake"


class FakeSignals:
    Position = FakePosition

    def __init__(self) -> None:
        self.script: list[str] = []
        self.stop: tuple[str, float] | None = None
        self.decisions = 0

    def decide(self, spec, bars, position):
        self.decisions += 1
        return FakeDecision(self.script.pop(0) if self.script else "hold")

    def stop_reason(self, spec, position, bar_open, bar_high, bar_low):
        return self.stop

    def closed_bars(self, bars, interval, now):
        return [b for b in bars if b[0] + 3600 <= now]


@dataclass
class FakeSpec:
    fee_bps: float = 10.0
    slippage_bps: float = 5.0
    size_pct: float = 50.0


def install_fake_lab(monkeypatch, spec: FakeSpec | None = None) -> FakeSignals:
    import parable.lab as lab

    signals = FakeSignals()
    chosen = spec or FakeSpec()
    module = types.ModuleType("parable.lab.spec")
    module.required_bars = lambda s: 300
    module.load_spec = lambda version_id: chosen
    monkeypatch.setitem(sys.modules, "parable.lab.spec", module)
    monkeypatch.setitem(sys.modules, "parable.lab.signals", signals)
    monkeypatch.setattr(lab, "spec", module, raising=False)
    monkeypatch.setattr(lab, "signals", signals, raising=False)
    return signals
