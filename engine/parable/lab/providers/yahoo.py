import re
import time

import httpx

from parable.lab.markets import MarketDataError, Quote, SymbolInfo
from parable.lab.popular import STOCK_INTERVALS, popular_static
from parable.lab.providers.base import clip, fetch_json, number

BASE = "https://query1.finance.yahoo.com"
CODE = re.compile(r"^[A-Za-z0-9.^=\-]{1,15}$")
INTERVAL_MAP = {"1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m", "1h": "60m", "1d": "1d", "1w": "1wk"}
RANGE_MAP = {"1m": "7d", "5m": "60d", "15m": "60d", "30m": "60d", "1h": "730d", "1d": "10y", "1w": "max"}
KIND_MAP = {"EQUITY": "stocks", "ETF": "stocks", "MUTUALFUND": "funds", "INDEX": "stocks"}


def kind_of(code: str, instrument: str) -> str:
    if code.upper() in ("GC=F", "XAUUSD=X"):
        return "gold"
    return KIND_MAP.get(instrument.upper(), "stocks")


def at(seq, index: int):
    return seq[index] if isinstance(seq, list) and index < len(seq) else None


class YahooProvider:
    id = "yahoo"
    kinds = ("stocks", "funds", "gold")
    intervals = tuple(STOCK_INTERVALS)

    def __init__(self, transport: httpx.BaseTransport | None = None) -> None:
        self.transport = transport

    def get(self, path: str, params: dict):
        return fetch_json(self.transport, "yahoo", f"{BASE}{path}", params)

    def chart(self, code: str, params: dict) -> dict:
        if not CODE.match(code):
            raise MarketDataError("unknown yahoo symbol", 404)
        data = self.get(f"/v8/finance/chart/{code}", params)
        chart = data.get("chart") if isinstance(data, dict) else None
        result = (chart or {}).get("result") if chart else None
        if not result:
            raise MarketDataError("yahoo has no data for that symbol", 404)
        return result[0]

    def make_info(self, code: str, meta: dict) -> SymbolInfo:
        name = meta.get("longName") or meta.get("shortName") or code
        return SymbolInfo(f"yahoo:{code}", str(name), kind_of(code, str(meta.get("instrumentType", ""))),
                          str(meta.get("currency") or "USD").upper(), "yahoo", list(self.intervals), True)

    def search(self, query: str, kind: str) -> list[SymbolInfo]:
        data = self.get("/v1/finance/search", {"q": query, "quotesCount": 12, "newsCount": 0})
        out = []
        for item in data.get("quotes", []) if isinstance(data, dict) else []:
            code = str(item.get("symbol") or "")
            if not CODE.match(code) or item.get("quoteType") not in (*KIND_MAP, "FUTURE"):
                continue
            found = kind_of(code, str(item.get("quoteType")))
            if kind in ("all", found):
                name = item.get("longname") or item.get("shortname") or code
                out.append(SymbolInfo(f"yahoo:{code}", str(name), found, "USD", "yahoo", list(self.intervals), True))
        return out

    def candles(self, code: str, interval: str, limit: int, start: float | None, end: float | None):
        if interval not in INTERVAL_MAP:
            raise MarketDataError(f"yahoo has no {interval} candles", 404)
        params = {"interval": INTERVAL_MAP[interval], "includePrePost": "false"}
        if start is not None or end is not None:
            params["period1"] = int(start or 0)
            params["period2"] = int(end or time.time() + 86400)
        else:
            params["range"] = RANGE_MAP[interval]
        result = self.chart(code, params)
        quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
        bars = []
        for i, t in enumerate(result.get("timestamp") or []):
            row = [number(at(quote.get(k), i)) for k in ("open", "high", "low", "close")]
            if None in row or t is None:
                continue
            volume = number(at(quote.get("volume"), i)) or 0.0
            bars.append([float(t), *row, volume])
        bars.sort(key=lambda b: b[0])
        return clip(bars, limit, start, end)

    def latest(self, code: str) -> Quote:
        meta = self.chart(code, {"interval": "1d", "range": "5d"}).get("meta") or {}
        price = number(meta.get("regularMarketPrice"))
        if price is None or price <= 0:
            raise MarketDataError("yahoo sent no price")
        t = number(meta.get("regularMarketTime")) or time.time()
        return Quote(f"yahoo:{code}", price, t, str(meta.get("currency") or "USD").upper(), time.time() - t > 4 * 86400)

    def info(self, code: str) -> SymbolInfo | None:
        try:
            return self.make_info(code, self.chart(code, {"interval": "1d", "range": "5d"}).get("meta") or {})
        except MarketDataError as err:
            if err.status == 404:
                return None
            raise

    def popular(self, kind: str) -> list[SymbolInfo]:
        return [i for i in popular_static(kind) if i.provider == self.id]
