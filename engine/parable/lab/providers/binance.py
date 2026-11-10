import re
import time

import httpx

from parable.lab.consts import INTERVAL_SECONDS
from parable.lab.markets import MarketDataError, Quote, SymbolInfo
from parable.lab.popular import BINANCE_INTERVALS, popular_static
from parable.lab.providers.base import fetch_json, number

BASE = "https://data-api.binance.vision/api/v3"
PAGE = 1000
QUOTES = ("USDT", "USDC", "BTC", "ETH")
CODE = re.compile(r"^[A-Z0-9]{5,20}$")
LISTING_TTL_S = 3600
SEARCH_MAX = 20


class BinanceProvider:
    id = "binance"
    kinds = ("crypto", "gold")
    intervals = tuple(BINANCE_INTERVALS)

    def __init__(self, transport: httpx.BaseTransport | None = None) -> None:
        self.transport = transport
        self.listing: list[dict] = []
        self.listed_at = 0.0

    def get(self, path: str, params: dict | None = None):
        return fetch_json(self.transport, "binance", f"{BASE}{path}", params, missing=(400, 404))

    def make_info(self, code: str, base: str, quote: str) -> SymbolInfo:
        kind = "gold" if code == "PAXGUSDT" else "crypto"
        names = {i.symbol: i.name for i in popular_static("all")}
        name = names.get(f"binance:{code}") or f"{base}/{quote}"
        return SymbolInfo(f"binance:{code}", name, kind, quote, "binance", list(self.intervals), True)

    def symbols(self) -> list[dict]:
        if not self.listing or time.time() - self.listed_at > LISTING_TTL_S:
            data = self.get("/exchangeInfo", {"permissions": "SPOT"})
            self.listing = [s for s in data.get("symbols", []) if s.get("status") == "TRADING"
                            and s.get("quoteAsset") in QUOTES]
            self.listed_at = time.time()
        return self.listing

    def search(self, query: str, kind: str) -> list[SymbolInfo]:
        needle = query.strip().upper()
        found = []
        for item in self.symbols():
            if needle not in item["symbol"] and needle not in item.get("baseAsset", ""):
                continue
            info = self.make_info(item["symbol"], item["baseAsset"], item["quoteAsset"])
            if kind in ("all", info.kind):
                found.append(info)
            if len(found) >= SEARCH_MAX:
                break
        return sorted(found, key=lambda i: (i.quote != "USDT", i.symbol))

    def page(self, code: str, interval: str, size: int, start_ms: int | None, end_ms: int | None) -> list[list[float]]:
        params = {"symbol": code, "interval": interval, "limit": size}
        if start_ms is not None:
            params["startTime"] = start_ms
        if end_ms is not None:
            params["endTime"] = end_ms
        rows = self.get("/klines", params)
        out = []
        for row in rows if isinstance(rows, list) else []:
            values = [number(x) for x in row[1:6]]
            if None in values:
                continue
            out.append([float(row[0]) / 1000.0, *values])
        return out

    def candles(self, code: str, interval: str, limit: int, start: float | None, end: float | None):
        if interval not in INTERVAL_SECONDS or interval not in self.intervals:
            raise MarketDataError(f"binance has no {interval} candles", 404)
        if not CODE.match(code):
            raise MarketDataError("unknown binance symbol", 404)
        step_ms = INTERVAL_SECONDS[interval] * 1000
        end_ms = int(end * 1000) - 1 if end is not None else None
        rows: list[list[float]] = []
        cursor = int(start * 1000) if start is not None else None
        while len(rows) < limit:
            size = min(PAGE, limit - len(rows))
            got = self.page(code, interval, size, cursor, end_ms)
            if not got:
                break
            if start is not None:
                rows += got
                cursor = int(got[-1][0] * 1000) + step_ms
            else:
                rows = got + rows
                end_ms = int(got[0][0] * 1000) - 1
            if len(got) < size:
                break
        return rows

    def latest(self, code: str) -> Quote:
        if not CODE.match(code):
            raise MarketDataError("unknown binance symbol", 404)
        data = self.get("/ticker/price", {"symbol": code})
        price = number(data.get("price")) if isinstance(data, dict) else None
        if price is None or price <= 0:
            raise MarketDataError("binance sent no price")
        quote = next((q for q in QUOTES if code.endswith(q) and len(code) > len(q)), "USDT")
        return Quote(f"binance:{code}", price, time.time(), quote, False)

    def info(self, code: str) -> SymbolInfo | None:
        if not CODE.match(code):
            return None
        try:
            data = self.get("/exchangeInfo", {"symbol": code})
        except MarketDataError as err:
            if err.status == 404:
                return None
            raise
        items = data.get("symbols", []) if isinstance(data, dict) else []
        if not items or items[0].get("quoteAsset") not in QUOTES:
            return None
        return self.make_info(code, items[0]["baseAsset"], items[0]["quoteAsset"])

    def popular(self, kind: str) -> list[SymbolInfo]:
        return [i for i in popular_static(kind) if i.provider == self.id]
