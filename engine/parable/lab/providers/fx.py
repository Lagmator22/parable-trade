import re
import time
from datetime import date, datetime, timedelta, timezone

import httpx

from parable.lab.markets import MarketDataError, Quote, SymbolInfo
from parable.lab.popular import popular_static
from parable.lab.providers.base import clip, fetch_json, number

BASE = "https://api.frankfurter.dev/v1"
CURRENCIES = ("USD", "EUR", "GBP", "JPY", "INR", "CHF", "AUD", "CAD", "CNY")
CODE = re.compile(r"^[A-Z]{6}$")
WINDOW_DAYS = 700
MAX_WINDOWS = 12


def split_pair(code: str) -> tuple[str, str]:
    if not CODE.match(code) or code[:3] not in CURRENCIES or code[3:] not in CURRENCIES or code[:3] == code[3:]:
        raise MarketDataError("unsupported currency pair", 404)
    return code[:3], code[3:]


class FxProvider:
    id = "fx"
    kinds = ("forex",)
    intervals = ("1d",)

    def __init__(self, transport: httpx.BaseTransport | None = None) -> None:
        self.transport = transport

    def get(self, path: str, params: dict):
        return fetch_json(self.transport, "frankfurter", f"{BASE}{path}", params)

    def make_info(self, code: str) -> SymbolInfo:
        base, quote = split_pair(code)
        return SymbolInfo(f"fx:{code}", f"{base} / {quote}", "forex", quote, "fx", ["1d"], True)

    def search(self, query: str, kind: str) -> list[SymbolInfo]:
        needle = re.sub(r"[^A-Z]", "", query.upper())
        pairs = [a + b for a in CURRENCIES for b in CURRENCIES if a != b]
        return [self.make_info(p) for p in pairs if needle and needle in p][:20]

    def series(self, base: str, quote: str, first: date, last: date) -> list[list[float]]:
        data = self.get(f"/{first.isoformat()}..{last.isoformat()}", {"base": base, "symbols": quote})
        out = []
        for day, rates in (data.get("rates", {}) if isinstance(data, dict) else {}).items():
            value = number((rates or {}).get(quote))
            if value is None or value <= 0:
                continue
            t = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()
            out.append([t, value, value, value, value, 0.0])
        return out

    def candles(self, code: str, interval: str, limit: int, start: float | None, end: float | None):
        base, quote = split_pair(code)
        if interval != "1d":
            raise MarketDataError("forex data is daily only", 404)
        last = datetime.fromtimestamp((end - 1) if end is not None else time.time(), timezone.utc).date()
        bars: list[list[float]] = []
        if start is not None:
            cursor = datetime.fromtimestamp(start, timezone.utc).date()
            for _ in range(MAX_WINDOWS):
                if cursor > last or len(bars) >= limit:
                    break
                stop = min(last, cursor + timedelta(days=WINDOW_DAYS))
                bars += self.series(base, quote, cursor, stop)
                cursor = stop + timedelta(days=1)
        else:
            cursor_end = last
            for _ in range(MAX_WINDOWS):
                first = cursor_end - timedelta(days=WINDOW_DAYS)
                got = self.series(base, quote, first, cursor_end)
                if not got:
                    break
                bars = got + [b for b in bars if b[0] > got[-1][0]]
                if len(bars) >= limit:
                    break
                cursor_end = first - timedelta(days=1)
        bars.sort(key=lambda b: b[0])
        return clip(bars, limit, start, end)

    def latest(self, code: str) -> Quote:
        base, quote = split_pair(code)
        data = self.get("/latest", {"base": base, "symbols": quote})
        rate = number(((data or {}).get("rates") or {}).get(quote)) if isinstance(data, dict) else None
        if rate is None or rate <= 0:
            raise MarketDataError("frankfurter sent no rate")
        return Quote(f"fx:{code}", rate, time.time(), quote, False)

    def info(self, code: str) -> SymbolInfo | None:
        try:
            return self.make_info(code)
        except MarketDataError:
            return None

    def popular(self, kind: str) -> list[SymbolInfo]:
        return [i for i in popular_static(kind) if i.provider == self.id]
