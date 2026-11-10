import math
from typing import Any

import httpx

from parable.lab.markets import MarketDataError

TIMEOUT_S = 8
USER_AGENT = "Mozilla/5.0 (compatible; ParableLab/1.0)"


def fetch_json(transport: httpx.BaseTransport | None, provider: str, url: str, params: dict | None = None,
               missing: tuple[int, ...] = (404,), headers: dict | None = None) -> Any:
    response = None
    try:
        with httpx.Client(timeout=TIMEOUT_S, transport=transport, headers={"User-Agent": USER_AGENT, **(headers or {})}) as client:
            response = client.get(url, params=params)
    except httpx.HTTPError:
        pass
    if response is None:
        raise MarketDataError(f"{provider} is unreachable")
    if response.status_code in missing:
        raise MarketDataError(f"{provider} does not know that symbol", 404)
    if response.status_code == 429:
        raise MarketDataError(f"{provider} is rate limiting us, try again shortly")
    if response.status_code >= 400:
        raise MarketDataError(f"{provider} answered HTTP {response.status_code}")
    try:
        return response.json()
    except ValueError:
        pass
    raise MarketDataError(f"{provider} sent an unreadable answer")


def number(value: Any) -> float | None:
    try:
        parsed = float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def clip(bars: list[list[float]], limit: int, start: float | None, end: float | None) -> list[list[float]]:
    kept = [bar for bar in bars if (start is None or bar[0] >= start) and (end is None or bar[0] < end)]
    return kept[:limit] if start is not None and end is None else kept[-limit:]
