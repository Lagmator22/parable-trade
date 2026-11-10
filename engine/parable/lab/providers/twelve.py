import re
import time
from datetime import datetime, timezone

import httpx

from parable.config import get_settings
from parable.lab.markets import MarketDataError, Quote, SymbolInfo
from parable.lab.popular import TWELVE_INTERVALS, popular_static
from parable.lab.providers.base import clip, fetch_json, number

BASE = "https://api.twelvedata.com"
CODE = re.compile(r"^[A-Za-z0-9.\-]{1,15}$")
INTERVAL_MAP = {"1m": "1min", "5m": "5min", "15m": "15min", "30m": "30min", "1h": "1h", "4h": "4h",
                "1d": "1day", "1w": "1week"}
MAX_OUTPUT = 5000


def parse_time(text: str) -> float | None:
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc).timestamp()
        except (TypeError, ValueError):
            continue
    return None


class TwelveProvider:
    id = "twelve"
    kinds = ("stocks",)
    intervals = tuple(TWELVE_INTERVALS)

    def __init__(self, transport: httpx.BaseTransport | None = None) -> None:
        self.transport = transport

    def get(self, path: str, params: dict):
        key = get_settings().twelve_data_key
        if not key:
            raise MarketDataError("twelve data is not configured")
        data = fetch_json(self.transport, "twelve", f"{BASE}{path}", params,
                          headers={"Authorization": f"apikey {key}"})
        if isinstance(data, dict) and data.get("status") == "error":
            code = data.get("code")
            raise MarketDataError("twelve data does not know that symbol" if code in (400, 404)
                                  else "twelve data refused the request", 404 if code in (400, 404) else 502)
        return data

    def search(self, query: str, kind: str) -> list[SymbolInfo]:
        data = self.get("/symbol_search", {"symbol": query, "outputsize": 12})
        out = []
        for item in data.get("data", []) if isinstance(data, dict) else []:
            code = str(item.get("symbol") or "")
            if CODE.match(code) and str(item.get("instrument_type", "")) in ("Common Stock", "ETF", "Depositary Receipt"):
                out.append(SymbolInfo(f"twelve:{code}", str(item.get("instrument_name") or code), "stocks",
                                      str(item.get("currency") or "USD").upper(), "twelve", list(self.intervals), True))
        return out

    def candles(self, code: str, interval: str, limit: int, start: float | None, end: float | None):
        if interval not in INTERVAL_MAP:
            raise MarketDataError(f"twelve data has no {interval} candles", 404)
        if not CODE.match(code):
            raise MarketDataError("unknown symbol", 404)
        size = min(limit, MAX_OUTPUT)
        params = {"symbol": code, "interval": INTERVAL_MAP[interval], "outputsize": size, "timezone": "UTC",
                  "order": "asc" if start is not None else "desc"}
        if start is not None:
            params["start_date"] = datetime.fromtimestamp(start, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        if end is not None:
            params["end_date"] = datetime.fromtimestamp(end, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        data = self.get("/time_series", params)
        bars = []
        for row in data.get("values", []) if isinstance(data, dict) else []:
            t = parse_time(row.get("datetime"))
            vals = [number(row.get(k)) for k in ("open", "high", "low", "close")]
            if t is None or None in vals:
                continue
            bars.append([t, *vals, number(row.get("volume")) or 0.0])
        bars.sort(key=lambda b: b[0])
        return clip(bars, size, start, end)

    def latest(self, code: str) -> Quote:
        if not CODE.match(code):
            raise MarketDataError("unknown symbol", 404)
        data = self.get("/price", {"symbol": code})
        price = number(data.get("price")) if isinstance(data, dict) else None
        if price is None or price <= 0:
            raise MarketDataError("twelve data sent no price")
        return Quote(f"twelve:{code}", price, time.time(), "USD", False)

    def info(self, code: str) -> SymbolInfo | None:
        for item in self.search(code, "stocks"):
            if item.symbol.upper() == f"twelve:{code}".upper():
                return item
        return None

    def popular(self, kind: str) -> list[SymbolInfo]:
        return [i for i in popular_static(kind, "twelve") if i.provider == self.id]
