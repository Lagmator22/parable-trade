import logging
import time

import httpx
import pytest

from parable.config import get_settings
from parable.lab.markets import MarketDataError
from parable.lab.providers.binance import BinanceProvider
from parable.lab.providers.fx import FxProvider
from parable.lab.providers.mfapi import MfapiProvider
from parable.lab.providers.twelve import TwelveProvider
from parable.lab.providers.yahoo import YahooProvider


def mock(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


def kline(t_s: int, price: float) -> list:
    ms = t_s * 1000
    return [ms, str(price), str(price + 2), str(price - 2), str(price + 1), "10.5", ms + 999, "0", 1, "0", "0", "0"]


def test_binance_single_page_parse():
    seen = []

    def handler(request):
        seen.append(dict(request.url.params))
        assert request.url.host == "data-api.binance.vision" and request.url.path == "/api/v3/klines"
        return httpx.Response(200, json=[kline(1_700_000_000, 100.0), kline(1_700_003_600, 101.0)])

    bars = BinanceProvider(mock(handler)).candles("BTCUSDT", "1h", 2, None, None)
    assert bars == [[1_700_000_000.0, 100.0, 102.0, 98.0, 101.0, 10.5], [1_700_003_600.0, 101.0, 103.0, 99.0, 102.0, 10.5]]
    assert seen[0]["symbol"] == "BTCUSDT" and seen[0]["interval"] == "1h" and seen[0]["limit"] == "2"


def test_binance_pages_backwards_for_latest_bars():
    base = 1_700_000_000
    all_rows = [kline(base + i * 3600, 100 + i) for i in range(2500)]
    calls = []

    def handler(request):
        params = request.url.params
        end = int(params["endTime"]) if "endTime" in params else 10**15
        size = int(params["limit"])
        calls.append(size)
        rows = [r for r in all_rows if r[0] <= end][-size:]
        return httpx.Response(200, json=rows)

    bars = BinanceProvider(mock(handler)).candles("BTCUSDT", "1h", 2100, None, None)
    assert len(bars) == 2100 and calls == [1000, 1000, 100]
    assert bars[-1][0] == base + 2499 * 3600
    assert all(a[0] < b[0] for a, b in zip(bars, bars[1:]))


def test_binance_pages_forward_from_start_and_honours_end():
    base = 1_700_000_000
    all_rows = [kline(base + i * 60, 100 + i) for i in range(1500)]

    def handler(request):
        params = request.url.params
        start = int(params.get("startTime", 0))
        end = int(params.get("endTime", 10**15))
        rows = [r for r in all_rows if start <= r[0] <= end][: int(params["limit"])]
        return httpx.Response(200, json=rows)

    provider = BinanceProvider(mock(handler))
    bars = provider.candles("BTCUSDT", "1m", 1200, base, None)
    assert len(bars) == 1200 and bars[0][0] == base
    bars = provider.candles("BTCUSDT", "1m", 5000, base, base + 600)
    assert len(bars) == 10 and bars[-1][0] == base + 540


def test_binance_one_second_candles_allowed():
    provider = BinanceProvider(mock(lambda r: httpx.Response(200, json=[kline(1_700_000_000, 5.0)])))
    assert provider.candles("BTCUSDT", "1s", 1, None, None)[0][0] == 1_700_000_000.0


def test_binance_errors_never_include_urls():
    def invalid(request):
        return httpx.Response(400, json={"code": -1121, "msg": "Invalid symbol."})

    with pytest.raises(MarketDataError) as err:
        BinanceProvider(mock(invalid)).candles("NOPEUSDT", "1h", 5, None, None)
    assert err.value.status == 404 and err.value.code == "not_found"

    def down(request):
        raise httpx.ConnectError("boom https://secret.example/?key=abc")

    with pytest.raises(MarketDataError) as err:
        BinanceProvider(mock(down)).latest("BTCUSDT")
    assert err.value.code == "data_unavailable" and "secret" not in err.value.detail

    with pytest.raises(MarketDataError) as err:
        BinanceProvider(mock(lambda r: httpx.Response(503))).latest("BTCUSDT")
    assert err.value.status == 502
    with pytest.raises(MarketDataError):
        BinanceProvider(mock(lambda r: httpx.Response(200, text="<html>"))).latest("BTCUSDT")
    with pytest.raises(MarketDataError):
        BinanceProvider(mock(lambda r: httpx.Response(200, json=[]))).candles("bad code!", "1h", 5, None, None)
    with pytest.raises(MarketDataError):
        BinanceProvider(mock(lambda r: httpx.Response(200, json=[]))).candles("BTCUSDT", "7m", 5, None, None)


def test_binance_latest_info_and_search():
    listing = {"symbols": [
        {"symbol": "BTCUSDT", "status": "TRADING", "baseAsset": "BTC", "quoteAsset": "USDT"},
        {"symbol": "BTCEUR", "status": "TRADING", "baseAsset": "BTC", "quoteAsset": "EUR"},
        {"symbol": "ETHBTC", "status": "TRADING", "baseAsset": "ETH", "quoteAsset": "BTC"},
        {"symbol": "OLDUSDT", "status": "BREAK", "baseAsset": "OLD", "quoteAsset": "USDT"},
        {"symbol": "PAXGUSDT", "status": "TRADING", "baseAsset": "PAXG", "quoteAsset": "USDT"}]}
    hits = {"info": 0}

    def handler(request):
        if request.url.path.endswith("/ticker/price"):
            return httpx.Response(200, json={"symbol": "BTCUSDT", "price": "73723.43"})
        hits["info"] += 1
        if "symbol" in request.url.params:
            return httpx.Response(200, json={"symbols": [s for s in listing["symbols"] if s["symbol"] == request.url.params["symbol"]]})
        return httpx.Response(200, json=listing)

    provider = BinanceProvider(mock(handler))
    quote = provider.latest("BTCUSDT")
    assert quote.price == 73723.43 and quote.quote == "USDT" and quote.symbol == "binance:BTCUSDT" and not quote.stale
    assert abs(quote.t - time.time()) < 5
    found = provider.search("btc", "all")
    assert [i.symbol for i in found] == ["binance:BTCUSDT", "binance:ETHBTC"]
    assert provider.search("paxg", "crypto") == []
    assert provider.search("paxg", "gold")[0].kind == "gold"
    provider.search("eth", "all")
    assert hits["info"] == 1
    info = provider.info("BTCUSDT")
    assert info.name == "Bitcoin" and info.kind == "crypto" and "1s" in info.intervals and info.live
    assert provider.info("PAXGUSDT").kind == "gold"
    assert provider.info("BTCEUR") is None
    assert [i.symbol for i in provider.popular("gold")] == ["binance:PAXGUSDT"]


MF_DATA = {"meta": {"scheme_name": "Test Fund", "scheme_code": 125497},
           "data": [{"date": "05-01-2024", "nav": "12.5"}, {"date": "04-01-2024", "nav": "12.0"},
                    {"date": "03-01-2024", "nav": "bad"}, {"date": "02-01-2024", "nav": "11.0"}], "status": "SUCCESS"}


def test_mfapi_candles_sorted_filtered_and_flat():
    provider = MfapiProvider(mock(lambda r: httpx.Response(200, json=MF_DATA)))
    bars = provider.candles("125497", "1d", 10, None, None)
    assert bars == [[1704153600.0, 11.0, 11.0, 11.0, 11.0, 0.0], [1704326400.0, 12.0, 12.0, 12.0, 12.0, 0.0],
                    [1704412800.0, 12.5, 12.5, 12.5, 12.5, 0.0]]
    assert len(provider.candles("125497", "1d", 1, None, None)) == 1
    assert [b[1] for b in provider.candles("125497", "1d", 10, 1704326400, None)] == [12.0, 12.5]
    with pytest.raises(MarketDataError):
        provider.candles("125497", "1h", 10, None, None)
    with pytest.raises(MarketDataError):
        provider.candles("abc", "1d", 10, None, None)


def test_mfapi_search_latest_info():
    def handler(request):
        if request.url.path == "/mf/search":
            assert request.url.params["q"] == "sbi"
            return httpx.Response(200, json=[{"schemeCode": 1, "schemeName": "A"}, {"schemeCode": 2}])
        return httpx.Response(200, json={"meta": MF_DATA["meta"], "data": [MF_DATA["data"][0]]})

    provider = MfapiProvider(mock(handler))
    assert [i.symbol for i in provider.search("sbi", "funds")] == ["mfapi:1"]
    quote = provider.latest("125497")
    assert quote.price == 12.5 and quote.quote == "INR" and quote.stale
    info = provider.info("125497")
    assert info.name == "Test Fund" and info.quote == "INR" and info.intervals == ["1d"]
    assert len(provider.popular("funds")) == 6


def test_mfapi_unknown_fund_is_not_found():
    provider = MfapiProvider(mock(lambda r: httpx.Response(404, json={"status": "ERROR"})))
    assert provider.info("999999") is None
    with pytest.raises(MarketDataError) as err:
        provider.candles("999999", "1d", 5, None, None)
    assert err.value.status == 404


def test_fx_candles_windows_latest_and_validation():
    windows = []

    def handler(request):
        if request.url.path.endswith("/latest"):
            assert request.url.params["base"] == "EUR" and request.url.params["symbols"] == "USD"
            return httpx.Response(200, json={"amount": 1.0, "base": "EUR", "date": "2026-11-10", "rates": {"USD": 1.12}})
        span = request.url.path.rsplit("/", 1)[1]
        first, last = span.split("..")
        windows.append((first, last))
        return httpx.Response(200, json={"rates": {first: {"USD": 1.1}, last: {"USD": 1.2}}})

    provider = FxProvider(mock(handler))
    bars = provider.candles("EURUSD", "1d", 3, None, 1_700_000_000)
    assert len(bars) == 3 and bars == sorted(bars)
    assert all(b[1] == b[2] == b[3] == b[4] and b[5] == 0.0 for b in bars)
    assert len(windows) >= 2
    quote = provider.latest("EURUSD")
    assert quote.price == 1.12 and quote.quote == "USD"
    info = provider.info("USDINR")
    assert info.quote == "INR" and info.kind == "forex" and info.name == "USD / INR"
    for bad in ("EURXXX", "EUREUR", "EUR"):
        assert provider.info(bad) is None
        with pytest.raises(MarketDataError):
            provider.candles(bad, "1d", 5, None, None)
    assert "fx:EURUSD" in [i.symbol for i in provider.search("eur", "forex")]
    assert len(provider.popular("forex")) == 5


def test_fx_start_forward_paging():
    def handler(request):
        first, last = request.url.path.rsplit("/", 1)[1].split("..")
        return httpx.Response(200, json={"rates": {first: {"JPY": 150.0}}})

    bars = FxProvider(mock(handler)).candles("USDJPY", "1d", 50, 1_600_000_000, 1_700_000_000)
    assert bars and bars[0][0] >= 1_600_000_000 - 86400 * 2 and all(b[4] == 150.0 for b in bars)


YAHOO_CHART = {"chart": {"result": [{
    "meta": {"currency": "USD", "symbol": "AAPL", "longName": "Apple Inc.", "instrumentType": "EQUITY",
             "regularMarketPrice": 190.5, "regularMarketTime": int(time.time())},
    "timestamp": [1_700_000_000, 1_700_086_400, 1_700_172_800, 1_700_259_200],
    "indicators": {"quote": [{"open": [1, 2, None, 4], "high": [2, 3, 4, 5], "low": [0.5, 1, 2, 3],
                              "close": [1.5, 2.5, 3.5, 4.5], "volume": [100, None, 300, 400]}]}}], "error": None}}


def test_yahoo_chart_parsing_drops_null_rows():
    seen = {}

    def handler(request):
        seen.update(dict(request.url.params))
        return httpx.Response(200, json=YAHOO_CHART)

    bars = YahooProvider(mock(handler)).candles("AAPL", "1d", 10, None, None)
    assert bars == [[1_700_000_000.0, 1.0, 2.0, 0.5, 1.5, 100.0], [1_700_086_400.0, 2.0, 3.0, 1.0, 2.5, 0.0],
                    [1_700_259_200.0, 4.0, 5.0, 3.0, 4.5, 400.0]]
    assert seen["interval"] == "1d" and seen["range"] == "10y"
    bars = YahooProvider(mock(handler)).candles("AAPL", "1h", 10, 1_700_000_000, 1_700_300_000)
    assert seen["interval"] == "60m" and seen["period1"] == "1700000000" and bars


def test_yahoo_info_latest_search_and_failures():
    def handler(request):
        if request.url.path == "/v1/finance/search":
            return httpx.Response(200, json={"quotes": [
                {"symbol": "AAPL", "shortname": "Apple", "quoteType": "EQUITY"},
                {"symbol": "VFIAX", "longname": "Vanguard 500", "quoteType": "MUTUALFUND"},
                {"symbol": "AAPL.X", "quoteType": "CRYPTOCURRENCY"}]})
        if "NOPE" in request.url.path:
            return httpx.Response(404, json={"chart": {"result": None, "error": {"code": "Not Found"}}})
        return httpx.Response(200, json=YAHOO_CHART)

    provider = YahooProvider(mock(handler))
    assert [(i.symbol, i.kind) for i in provider.search("apple", "all")] == [("yahoo:AAPL", "stocks"), ("yahoo:VFIAX", "funds")]
    assert [i.symbol for i in provider.search("apple", "funds")] == ["yahoo:VFIAX"]
    info = provider.info("AAPL")
    assert info.name == "Apple Inc." and info.quote == "USD" and "1w" in info.intervals
    assert provider.info("NOPE") is None
    quote = provider.latest("AAPL")
    assert quote.price == 190.5 and not quote.stale
    with pytest.raises(MarketDataError) as err:
        YahooProvider(mock(lambda r: httpx.Response(429, text="Too Many Requests"))).candles("AAPL", "1d", 5, None, None)
    assert err.value.code == "data_unavailable"
    with pytest.raises(MarketDataError):
        provider.candles("AAPL", "4h", 5, None, None)
    with pytest.raises(MarketDataError):
        provider.candles("bad symbol", "1d", 5, None, None)
    assert [i.symbol for i in provider.popular("stocks")][:2] == ["yahoo:AAPL", "yahoo:MSFT"]


@pytest.fixture
def twelve_key(monkeypatch):
    monkeypatch.setenv("TWELVE_DATA_KEY", "tw-secret-key-123")
    get_settings.cache_clear()
    return "tw-secret-key-123"


def test_twelve_parsing_and_key_use(twelve_key):
    seen = {}

    def handler(request):
        seen.update(dict(request.url.params))
        seen["auth"] = request.headers["authorization"]
        if request.url.path == "/symbol_search":
            return httpx.Response(200, json={"data": [
                {"symbol": "AAPL", "instrument_name": "Apple Inc", "instrument_type": "Common Stock", "currency": "USD"},
                {"symbol": "BTC", "instrument_name": "Bitcoin", "instrument_type": "Digital Currency", "currency": "USD"}]})
        if request.url.path == "/price":
            return httpx.Response(200, json={"price": "190.12"})
        return httpx.Response(200, json={"values": [
            {"datetime": "2024-01-03", "open": "2", "high": "3", "low": "1", "close": "2.5", "volume": "50"},
            {"datetime": "2024-01-02 15:30:00", "open": "1", "high": "2", "low": "0.5", "close": "1.5"}]})

    provider = TwelveProvider(mock(handler))
    bars = provider.candles("AAPL", "1d", 100, None, None)
    assert bars == [[1704209400.0, 1.0, 2.0, 0.5, 1.5, 0.0], [1704240000.0, 2.0, 3.0, 1.0, 2.5, 50.0]]
    assert seen["auth"] == f"apikey {twelve_key}" and "apikey" not in seen and seen["interval"] == "1day" and seen["order"] == "desc"
    assert [i.symbol for i in provider.search("apple", "stocks")] == ["twelve:AAPL"]
    assert provider.latest("AAPL").price == 190.12
    assert provider.info("AAPL").name == "Apple Inc"
    assert provider.info("ZZZZ") is None
    assert provider.popular("stocks")[0].symbol == "twelve:AAPL"


def test_twelve_errors_and_key_never_leak(twelve_key, caplog):
    caplog.set_level(logging.DEBUG)

    def api_error(request):
        return httpx.Response(200, json={"code": 401, "message": f"bad apikey {twelve_key}", "status": "error"})

    def down(request):
        raise httpx.ConnectError(f"cannot reach {request.url}")

    def server(request):
        return httpx.Response(500, text=f"oops {twelve_key}")

    for handler in (api_error, down, server):
        with pytest.raises(MarketDataError) as err:
            TwelveProvider(mock(handler)).candles("AAPL", "1d", 5, None, None)
        assert twelve_key not in str(err.value) and twelve_key not in err.value.detail
        assert err.value.__cause__ is None and err.value.__context__ is None
    assert twelve_key not in caplog.text


def test_twelve_missing_key_and_unknown_symbol(monkeypatch):
    monkeypatch.setenv("TWELVE_DATA_KEY", "")
    get_settings.cache_clear()
    with pytest.raises(MarketDataError):
        TwelveProvider(mock(lambda r: httpx.Response(200, json={}))).latest("AAPL")
    monkeypatch.setenv("TWELVE_DATA_KEY", "k")
    get_settings.cache_clear()
    gone = TwelveProvider(mock(lambda r: httpx.Response(200, json={"code": 400, "status": "error", "message": "x"})))
    with pytest.raises(MarketDataError) as err:
        gone.candles("AAPL", "1d", 5, None, None)
    assert err.value.status == 404
