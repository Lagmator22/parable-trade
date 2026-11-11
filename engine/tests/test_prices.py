
import httpx
import pytest

from parable import prices
from parable.config import get_settings
from run_support import feed

SIM_START = prices.SIM_START


class FakeResponse:
    def __init__(self, payload: dict, status: int = 200) -> None:
        self.payload = payload
        self.status = status

    def raise_for_status(self) -> None:
        if self.status >= 400:
            raise httpx.HTTPStatusError("bad", request=None, response=None)

    def json(self) -> dict:
        return self.payload


def go_live(monkeypatch) -> None:
    monkeypatch.setenv("PRICE_SOURCE", "live")
    get_settings.cache_clear()
    prices.set_price_source(None)


def fake_get(responses: dict):
    calls = []

    def get(url, timeout=None):
        calls.append(url)
        for marker, outcome in responses.items():
            if marker in url:
                if isinstance(outcome, Exception):
                    raise outcome
                return outcome
        raise httpx.ConnectError("no route")

    get.calls = calls
    return get


COINBASE = {"data": {"amount": "3412.55"}}
KRAKEN = {"error": [], "result": {"XETHZUSD": {"c": ["3400.10", "1.0"]}}}
BINANCE = {"symbol": "ETHUSDT", "price": "3399.99000000"}


def test_to_price_uses_eight_decimals():
    assert prices.to_price("3412.55") == 341_255_000_000
    assert prices.to_price(1) == 100_000_000


def test_sim_starts_near_3000_and_steps_are_bounded():
    previous = SIM_START
    for _ in range(300):
        current = prices.sim_for_symbol()
        assert abs(current - previous) * 10_000 <= previous * (prices.SIM_MAX_STEP_BPS + 1)
        previous = current
    assert 2000 * 10**8 < previous < 4000 * 10**8




def test_sim_produces_both_ups_and_downs():
    series = [prices.sim_for_symbol() for _ in range(50)]
    moves = [b - a for a, b in zip(series, series[1:])]
    assert any(m > 0 for m in moves) and any(m < 0 for m in moves)


def test_set_price_source_overrides_and_resets():
    prices.set_price_source(lambda: 123 * 10**8)
    assert prices.price_for("fake:X") == 123 * 10**8
    prices.set_price_source(None)
    assert prices.price_for("fake:X") != 123 * 10**8




















def test_override_arity_is_inspected_for_both_paths():
    prices.set_price_source(lambda: 5 * 10**8)
    assert prices.price_for("fake:X") == 5 * 10**8
    seen = []
    prices.set_price_source(lambda symbol: seen.append(symbol) or 7 * 10**8)
    assert prices.price_for("fake:X") == 7 * 10**8 and prices.cached_price("fake:Y") == 7 * 10**8
    assert seen == ["fake:X", "fake:Y"]


def test_price_for_uses_latest_quote_live(feed, monkeypatch):
    go_live(monkeypatch)
    feed.price = 123.456789
    assert prices.price_for("fake:ABC") == 12345678900
    feed.price = 0
    from parable.lab import markets
    markets.clear_cache()
    with pytest.raises(ValueError):
        prices.price_for("fake:ABC")


def test_price_for_sim_prefers_offline_fake_then_simulates(feed):
    feed.price = 50.0
    assert prices.price_for("fake:ABC") == 50 * 10**8
    value = prices.price_for("binance:BTCUSDT")
    assert value > 0 and value != 50 * 10**8


def test_cached_price_never_fetches(feed):
    from parable.lab import markets
    assert prices.cached_price("fake:ABC") is None
    assert feed.calls == 0
    markets.latest("fake:ABC")
    feed.calls = 0
    assert prices.cached_price("fake:ABC") == 3000 * 10**8
    assert feed.calls == 0


def test_cached_price_unknown_symbol_is_none():
    assert prices.cached_price("nope:ABC") is None
    assert prices.cached_price("garbage") is None
