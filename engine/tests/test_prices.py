import time

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
    monkeypatch.setattr(prices, "CACHE_TTL_S", 0)
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


def test_sim_starts_near_3000_and_steps_are_bounded(monkeypatch):
    monkeypatch.setattr(prices, "CACHE_TTL_S", 0)
    previous = SIM_START
    for _ in range(300):
        current = prices.price()
        assert abs(current - previous) * 10_000 <= previous * (prices.SIM_MAX_STEP_BPS + 1)
        previous = current
    assert 2000 * 10**8 < previous < 4000 * 10**8


def test_sim_is_cached_for_two_seconds():
    first = prices.price()
    assert prices.price() == first
    assert prices.price() == first


def test_sim_produces_both_ups_and_downs(monkeypatch):
    monkeypatch.setattr(prices, "CACHE_TTL_S", 0)
    series = [prices.price() for _ in range(50)]
    moves = [b - a for a, b in zip(series, series[1:])]
    assert any(m > 0 for m in moves) and any(m < 0 for m in moves)


def test_set_price_source_overrides_and_resets():
    prices.set_price_source(lambda: 123 * 10**8)
    assert prices.price() == 123 * 10**8
    prices.set_price_source(None)
    assert prices.price() != 123 * 10**8


def test_live_prefers_coinbase(monkeypatch):
    go_live(monkeypatch)
    getter = fake_get({"coinbase": FakeResponse(COINBASE), "kraken": FakeResponse(KRAKEN)})
    monkeypatch.setattr(prices.httpx, "get", getter)
    assert prices.price() == 341_255_000_000
    assert len(getter.calls) == 1


def test_live_falls_back_to_kraken_then_binance(monkeypatch):
    go_live(monkeypatch)
    monkeypatch.setattr(prices.httpx, "get", fake_get({"kraken": FakeResponse(KRAKEN)}))
    assert prices.price() == 340_010_000_000
    monkeypatch.setattr(prices.httpx, "get", fake_get({"binance": FakeResponse(BINANCE)}))
    assert prices.price() == 339_999_000_000


def test_live_skips_bad_payloads_and_http_errors(monkeypatch):
    go_live(monkeypatch)
    responses = {"coinbase": FakeResponse({"oops": 1}), "kraken": FakeResponse(KRAKEN, status=500),
                 "binance": FakeResponse(BINANCE)}
    monkeypatch.setattr(prices.httpx, "get", fake_get(responses))
    assert prices.price() == 339_999_000_000


def test_live_failure_reuses_last_good_price(monkeypatch):
    go_live(monkeypatch)
    monkeypatch.setattr(prices.httpx, "get", fake_get({"coinbase": FakeResponse(COINBASE)}))
    assert prices.price() == 341_255_000_000
    monkeypatch.setattr(prices.httpx, "get", fake_get({}))
    assert prices.price() == 341_255_000_000


def test_live_failure_with_no_history_falls_back_to_sim(monkeypatch):
    go_live(monkeypatch)
    monkeypatch.setattr(prices.httpx, "get", fake_get({}))
    value = prices.price()
    assert abs(value - SIM_START) * 10_000 <= SIM_START * prices.SIM_MAX_STEP_BPS


def test_live_cache_avoids_second_fetch(monkeypatch):
    go_live(monkeypatch)
    monkeypatch.setattr(prices, "CACHE_TTL_S", 60)
    getter = fake_get({"coinbase": FakeResponse(COINBASE)})
    monkeypatch.setattr(prices.httpx, "get", getter)
    prices.price()
    prices.price()
    assert len(getter.calls) == 1


def test_history_records_samples_and_limits_length():
    assert prices.history() == []
    prices.set_price_source(lambda: 5 * 10**8)
    for _ in range(5):
        prices.record_sample()
    assert len(prices.history(3)) == 3
    assert len(prices.history()) == 5
    assert all(price == 5 * 10**8 for _, price in prices.history())
    assert prices.history(0) == []


def test_history_is_bounded():
    prices.set_price_source(lambda: 1)
    for _ in range(prices.HISTORY_LIMIT + 10):
        prices.record_sample()
    assert len(prices.history(10_000)) == prices.HISTORY_LIMIT


def test_sampler_thread_collects_and_stops(wait_until):
    prices.start_sampler(every_s=0.01)
    prices.start_sampler(every_s=0.01)
    assert wait_until(lambda: len(prices.history()) >= 3)
    prices.stop_sampler()
    count = len(prices.history(10_000))
    time.sleep(0.05)
    assert len(prices.history(10_000)) == count


def test_override_arity_is_inspected_for_both_paths():
    prices.set_price_source(lambda: 5 * 10**8)
    assert prices.price() == 5 * 10**8 and prices.price_for("fake:X") == 5 * 10**8
    seen = []
    prices.set_price_source(lambda symbol: seen.append(symbol) or 7 * 10**8)
    assert prices.price_for("fake:X") == 7 * 10**8 and prices.cached_price("fake:Y") == 7 * 10**8
    assert prices.price() == 7 * 10**8
    assert seen == ["fake:X", "fake:Y", "binance:ETHUSDT"]


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
