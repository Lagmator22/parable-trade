import math

TEST_ONLY = "synthetic bars for tests only, not market data"


def synthetic_bars(n: int = 600, *, seed: int = 7, start: float = 1_700_000_000.0,
                   step: float = 3600.0, base: float = 100.0, drift: float = 0.0004) -> list[list[float]]:
    state = seed * 2654435761 % 2**32
    price = base
    bars = []
    for i in range(n):
        state = (state * 1664525 + 1013904223) % 2**32
        noise = (state / 2**32 - 0.5) * 0.02
        wave = 0.012 * math.sin(i / 11.0) + 0.006 * math.sin(i / 3.7)
        close = price * (1 + drift + noise + wave * 0.3)
        high = max(price, close) * (1 + 0.003 + abs(noise) * 0.2)
        low = min(price, close) * (1 - 0.003 - abs(noise) * 0.2)
        bars.append([start + i * step, price, high, low, close, 1000.0 + (state % 500)])
        price = close
    return [[round(x, 6) for x in bar] for bar in bars]


def flat_bars(n: int = 40, price: float = 100.0, step: float = 3600.0) -> list[list[float]]:
    return [[1_700_000_000.0 + i * step, price, price, price, price, 10.0] for i in range(n)]


def make_bars(rows: list[tuple[float, float, float, float]], *, start: float = 1_700_000_000.0,
              step: float = 3600.0) -> list[list[float]]:
    return [[start + i * step, o, h, l, c, 10.0] for i, (o, h, l, c) in enumerate(rows)]


def columns_of(bars: list[list[float]]) -> dict[str, list[float]]:
    names = ("open", "high", "low", "close", "volume")
    return {name: [bar[i + 1] for bar in bars] for i, name in enumerate(names)}
