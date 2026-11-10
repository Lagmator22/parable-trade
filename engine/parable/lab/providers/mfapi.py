import re
import time
from datetime import datetime, timezone

import httpx

from parable.lab.markets import MarketDataError, Quote, SymbolInfo
from parable.lab.popular import popular_static
from parable.lab.providers.base import clip, fetch_json, number

BASE = "https://api.mfapi.in/mf"
CODE = re.compile(r"^\d{3,8}$")
SEARCH_MAX = 20


def day_epoch(text: str) -> float | None:
    try:
        return datetime.strptime(text, "%d-%m-%Y").replace(tzinfo=timezone.utc).timestamp()
    except (TypeError, ValueError):
        return None


class MfapiProvider:
    id = "mfapi"
    kinds = ("funds",)
    intervals = ("1d",)

    def __init__(self, transport: httpx.BaseTransport | None = None) -> None:
        self.transport = transport

    def get(self, url: str, params: dict | None = None):
        return fetch_json(self.transport, "mfapi", url, params)

    def make_info(self, code: str, name: str) -> SymbolInfo:
        return SymbolInfo(f"mfapi:{code}", name, "funds", "INR", "mfapi", ["1d"], True)

    def search(self, query: str, kind: str) -> list[SymbolInfo]:
        data = self.get(f"{BASE}/search", {"q": query})
        out = []
        for item in data if isinstance(data, list) else []:
            if item.get("schemeCode") and item.get("schemeName"):
                out.append(self.make_info(str(item["schemeCode"]), str(item["schemeName"])))
        return out[:SEARCH_MAX]

    def check(self, code: str) -> None:
        if not CODE.match(code):
            raise MarketDataError("unknown fund code", 404)

    def candles(self, code: str, interval: str, limit: int, start: float | None, end: float | None):
        self.check(code)
        if interval != "1d":
            raise MarketDataError("mfapi funds only have daily NAV", 404)
        data = self.get(f"{BASE}/{code}")
        bars = []
        for row in data.get("data", []) if isinstance(data, dict) else []:
            t, nav = day_epoch(row.get("date")), number(row.get("nav"))
            if t is not None and nav is not None and nav > 0:
                bars.append([t, nav, nav, nav, nav, 0.0])
        bars.sort(key=lambda b: b[0])
        if not bars:
            raise MarketDataError("that fund has no NAV history", 404)
        return clip(bars, limit, start, end)

    def latest(self, code: str) -> Quote:
        self.check(code)
        data = self.get(f"{BASE}/{code}/latest")
        rows = data.get("data", []) if isinstance(data, dict) else []
        nav = number(rows[0].get("nav")) if rows else None
        t = day_epoch(rows[0].get("date")) if rows else None
        if nav is None or t is None:
            raise MarketDataError("mfapi sent no NAV")
        return Quote(f"mfapi:{code}", nav, t, "INR", time.time() - t > 4 * 86400)

    def info(self, code: str) -> SymbolInfo | None:
        if not CODE.match(code):
            return None
        try:
            data = self.get(f"{BASE}/{code}/latest")
        except MarketDataError as err:
            if err.status == 404:
                return None
            raise
        name = (data.get("meta") or {}).get("scheme_name") if isinstance(data, dict) else None
        return self.make_info(code, str(name)) if name else None

    def popular(self, kind: str) -> list[SymbolInfo]:
        return [i for i in popular_static(kind) if i.provider == self.id]
