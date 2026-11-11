import json
from pathlib import Path

import pytest

from lab_support import FakeProvider, fake_market, finite, install_fake, make_bars
from parable.errors import LabError
from parable.lab import markets
from parable.lab.consts import MAX_BARS
from parable.lab.markets import MarketDataError
from parable.lab.providers import sample

SAMPLES = Path(sample.__file__).resolve().parent.parent / "samples"


class Clock:
    def __init__(self, t: float = 2_000_000_000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


def test_offline_registry_has_sample_and_upload_only():
    markets.reset_providers()
    assert set(markets.registry()) == {"sample", "upload"}


def test_online_registry_and_twelve_needs_key(monkeypatch):
    from parable.config import get_settings

    markets.reset_providers(offline=False)
    assert set(markets.registry()) == {"binance", "mfapi", "fx", "yahoo", "sample", "upload"}
    monkeypatch.setenv("TWELVE_DATA_KEY", "k-test")
    get_settings.cache_clear()
    markets.reset_providers(offline=False)
    assert "twelve" in markets.registry()
    markets.reset_providers(offline=True)


def test_popular_lists_work_offline():
    markets.reset_providers(offline=True)
    assert [i.symbol for i in markets.popular("crypto")] == [
        f"binance:{c}" for c in ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT")]
    assert [i.symbol for i in markets.popular("gold")] == ["binance:PAXGUSDT"]
    assert [i.symbol for i in markets.popular("forex")] == [
        f"fx:{c}" for c in ("EURUSD", "GBPUSD", "USDJPY", "USDINR", "AUDUSD")]
    assert [i.symbol for i in markets.popular("stocks")] == [f"yahoo:{c}" for c in ("AAPL", "MSFT", "NVDA", "TSLA", "SPY", "QQQ")]
    funds = markets.popular("funds")
    assert len(funds) == 6 and funds[0].symbol == "mfapi:125497" and funds[0].quote == "INR"
    assert markets.popular("mine") == []


def test_popular_stocks_use_twelve_when_only_twelve(fake_market):
    markets.unregister_provider("yahoo")
    markets.register_provider(FakeProvider("twelve", ("stocks",), bars_by_code={}))
    assert {i.provider for i in markets.popular("stocks")} == {"twelve"}


def test_search_merges_providers_by_kind(fake_market):
    markets.register_provider(FakeProvider("other", ("stocks",), "USD", bars_by_code={"BTCX": make_bars(40)}))
    assert "fake:BTCUSDT" in [i.symbol for i in markets.search("btc", "crypto")]
    assert "other:BTCX" not in [i.symbol for i in markets.search("btc", "crypto")]
    assert {"fake:BTCUSDT", "other:BTCX"} <= {i.symbol for i in markets.search("btc", "all")}
    assert markets.search("btc", "forex") == []
    assert markets.search("", "crypto")[0].provider == "binance"


def test_search_skips_failing_provider(fake_market):
    markets.register_provider(FakeProvider("broken", ("crypto",), bars_by_code={"BTCX": make_bars(40)}))
    markets.get_provider("broken").fail = True
    assert "fake:BTCUSDT" in [i.symbol for i in markets.search("btc", "crypto")]


def test_symbol_info_helpers(fake_market):
    info = markets.symbol_info("fake:BTCUSDT")
    assert info.quote == "USDT" and info.live
    assert markets.quote_currency("fake:BTCUSDT") == "USDT"
    assert markets.intervals_for("fake:BTCUSDT") == ["1m", "1h", "1d"]
    for bad in ("fake:NOPE", "nowhere:X", "BTCUSDT", "fake:"):
        with pytest.raises(MarketDataError) as err:
            markets.symbol_info(bad)
        assert err.value.status == 404 and err.value.code == "not_found"


def test_source_kind():
    assert markets.source_kind("sample:BTCUSDT") == "sample"
    assert markets.source_kind("upload:d_abc") == "creator"
    assert markets.source_kind("binance:BTCUSDT") == "market"


def test_candles_validation_drops_bad_rows(fake_market):
    good = make_bars(60)
    bad = [list(b) for b in good]
    bad[5][2] = bad[5][1] - 1
    bad[10][3] = bad[10][1] + 1
    bad[15][4] = float("nan")
    bad.insert(20, list(bad[19]))
    bad.append([bad[-1][0] - 5, 1, 1, 1, 1, 1])
    fake_market.bars_by_code["BTCUSDT"] = bad
    out = markets.candles("fake:BTCUSDT", "1h", 500)
    assert len(out) == 57 and finite(out)
    assert all(a[0] < b[0] for a, b in zip(out, out[1:]))
    assert all(b[2] >= max(b[1], b[4]) and b[3] <= min(b[1], b[4]) for b in out)


def test_candles_limit_start_end(fake_market):
    bars = fake_market.bars_by_code["BTCUSDT"]
    assert markets.candles("fake:BTCUSDT", "1h", 10) == bars[-10:]
    assert markets.candles("fake:BTCUSDT", "1h", 10, start=bars[100][0]) == bars[100:110]
    assert markets.candles("fake:BTCUSDT", "1h", 500, end=bars[50][0]) == bars[:50]
    assert markets.candles("fake:BTCUSDT", "1h", 500, start=bars[10][0], end=bars[20][0]) == bars[10:20]


def test_candles_argument_errors(fake_market):
    for kwargs in ({"interval": "7m"}, {"limit": 0}, {"limit": MAX_BARS + 1}):
        args = {"interval": "1h", "limit": 5, **kwargs}
        with pytest.raises(LabError) as err:
            markets.candles("fake:BTCUSDT", **args)
        assert err.value.code == "bad_request"


def test_candles_returns_copies(fake_market):
    first = markets.candles("fake:BTCUSDT", "1h", 5)
    first[0][1] = -1
    assert markets.candles("fake:BTCUSDT", "1h", 5)[0][1] != -1


def test_candle_cache_ttl_with_injected_clock(fake_market):
    clock = Clock()
    markets.set_clock(clock)
    for _ in range(3):
        markets.candles("fake:BTCUSDT", "1h", 50)
    assert fake_market.calls["candles"] == 1
    clock.t += 59
    markets.candles("fake:BTCUSDT", "1h", 50)
    assert fake_market.calls["candles"] == 1
    clock.t += 2
    markets.candles("fake:BTCUSDT", "1h", 50)
    assert fake_market.calls["candles"] == 2
    markets.candles("fake:BTCUSDT", "1m", 50)
    clock.t += 29
    markets.candles("fake:BTCUSDT", "1m", 50)
    assert fake_market.calls["candles"] == 3
    clock.t += 2
    markets.candles("fake:BTCUSDT", "1m", 50)
    assert fake_market.calls["candles"] == 4


def test_settled_history_cached_for_a_day(fake_market):
    clock = Clock()
    markets.set_clock(clock)
    end = clock.t - 10_000
    markets.candles("fake:BTCUSDT", "1h", 50, end=end)
    clock.t += 80_000
    markets.candles("fake:BTCUSDT", "1h", 50, end=end)
    assert fake_market.calls["candles"] == 1
    clock.t += 7_000
    markets.candles("fake:BTCUSDT", "1h", 50, end=end)
    assert fake_market.calls["candles"] == 2


def test_failures_cached_30_seconds(fake_market):
    clock = Clock()
    markets.set_clock(clock)
    fake_market.fail = True
    for _ in range(3):
        with pytest.raises(MarketDataError):
            markets.candles("fake:BTCUSDT", "1h", 50)
    assert fake_market.calls["candles"] == 1
    fake_market.fail = False
    clock.t += 31
    assert markets.candles("fake:BTCUSDT", "1h", 50)
    assert fake_market.calls["candles"] == 2


def test_cache_is_lru_bounded(fake_market):
    for limit in range(1, 300):
        markets.candles("fake:BTCUSDT", "1h", limit)
    assert len(markets._cache) <= 256


def test_latest_ttl_and_cached_only(fake_market):
    clock = Clock()
    markets.set_clock(clock)
    assert markets.latest("fake:BTCUSDT", cached_only=True) is None
    assert fake_market.calls["latest"] == 0
    quote = markets.latest("fake:BTCUSDT")
    assert quote.price == 100.0 and not quote.stale and quote.quote == "USDT"
    markets.latest("fake:BTCUSDT")
    assert fake_market.calls["latest"] == 1
    assert markets.latest("fake:BTCUSDT", cached_only=True).price == 100.0
    clock.t += 3600
    old = markets.latest("fake:BTCUSDT", cached_only=True)
    assert old.price == 100.0 and old.stale
    assert fake_market.calls["latest"] == 1


def test_latest_falls_back_to_last_good_when_provider_fails(fake_market):
    clock = Clock()
    markets.set_clock(clock)
    markets.latest("fake:BTCUSDT")
    fake_market.fail = True
    clock.t += 100
    assert markets.latest("fake:BTCUSDT").stale
    markets.reset_providers(offline=True)
    markets.register_provider(fake_market)
    with pytest.raises(MarketDataError):
        markets.latest("fake:BTCUSDT")


def test_binance_latest_ttl_is_five_seconds():
    fake = install_fake(provider_id="binance", kinds=("crypto",))
    clock = Clock()
    markets.set_clock(clock)
    markets.latest("binance:BTCUSDT")
    clock.t += 4
    markets.latest("binance:BTCUSDT")
    assert fake.calls["latest"] == 1
    clock.t += 2
    markets.latest("binance:BTCUSDT")
    assert fake.calls["latest"] == 2
    markets.set_clock(None)


def test_sample_files_match_sources_manifest():
    manifest = json.loads((SAMPLES / "SOURCES.json").read_text())
    assert manifest
    markets.reset_providers(offline=True)
    for name, meta in manifest.items():
        assert (SAMPLES / name).exists()
        assert meta["source_url"].startswith("https://") and meta["downloaded_at"]
        info = markets.symbol_info(meta["symbol"].replace(meta["provider"] + ":", "sample:"))
        assert not info.live and meta["interval"] in info.intervals
        bars = markets.candles(info.symbol, meta["interval"], MAX_BARS)
        assert len(bars) == meta["rows"] == len((SAMPLES / name).read_text().strip().splitlines()) - 1
        assert finite(bars)
    assert {f.name for f in SAMPLES.glob("*.csv")} == set(manifest)


def test_sample_provider_is_not_live_and_cached_only_latest_never_fetches():
    markets.reset_providers(offline=True)
    quote = markets.latest("sample:BTCUSDT")
    assert quote.stale and quote.quote == "USDT"
    markets.clear_cache()
    assert markets.latest("sample:BTCUSDT", cached_only=True) is None
    with pytest.raises(MarketDataError):
        markets.candles("sample:BTCUSDT", "1d", 10)


def test_closed_candles_drops_the_forming_bar(fake_market):
    bars = make_bars(40, start_t=1_700_000_000, interval_s=3600)
    fake_market.bars_by_code["BTCUSDT"] = bars
    markets.set_clock(lambda: bars[-1][0] + 1800)
    try:
        closed = markets.closed_candles("fake:BTCUSDT", "1h", 40)
        assert len(closed) == 39 and closed[-1][0] == bars[-2][0]
        markets.set_clock(lambda: bars[-1][0] + 3600)
        assert len(markets.closed_candles("fake:BTCUSDT", "1h", 40)) == 40
    finally:
        markets.set_clock(None)
