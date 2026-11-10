import math

Series = list


def _runs(src: Series, n: int, fn) -> Series:
    out: Series = [None] * len(src)
    run = 0
    for i, value in enumerate(src):
        run = run + 1 if value is not None else 0
        if run >= n:
            out[i] = fn(src[i - n + 1:i + 1])
    return out


def _smooth(src: Series, n: int, step) -> Series:
    out: Series = [None] * len(src)
    run = 0
    seed = 0.0
    prev = None
    for i, value in enumerate(src):
        if value is None:
            run, seed, prev = 0, 0.0, None
            continue
        run += 1
        if prev is None:
            seed += value
            if run == n:
                prev = seed / n
                out[i] = prev
            continue
        prev = step(prev, value)
        out[i] = prev
    return out


def sma(src: Series, n: int) -> Series:
    return _runs(src, n, lambda w: sum(w) / n)


def ema(src: Series, n: int) -> Series:
    alpha = 2.0 / (n + 1)
    return _smooth(src, n, lambda prev, x: prev + alpha * (x - prev))


def _wilder(src: Series, n: int) -> Series:
    return _smooth(src, n, lambda prev, x: (prev * (n - 1) + x) / n)


def _changes(src: Series) -> tuple[Series, Series]:
    gains: Series = [None] * len(src)
    losses: Series = [None] * len(src)
    for i in range(1, len(src)):
        if src[i] is None or src[i - 1] is None:
            continue
        delta = src[i] - src[i - 1]
        gains[i] = max(delta, 0.0)
        losses[i] = max(-delta, 0.0)
    return gains, losses


def _rsi_value(gain: float | None, loss: float | None) -> float | None:
    if gain is None or loss is None:
        return None
    if loss == 0:
        return 100.0 if gain > 0 else 50.0
    return 100.0 - 100.0 / (1.0 + gain / loss)


def rsi(src: Series, n: int) -> Series:
    gains, losses = _changes(src)
    avg_gain, avg_loss = _wilder(gains, n), _wilder(losses, n)
    return [_rsi_value(g, l) for g, l in zip(avg_gain, avg_loss)]


def _sub(a: Series, b: Series) -> Series:
    return [None if x is None or y is None else x - y for x, y in zip(a, b)]


def macd(src: Series, fast: int, slow: int) -> Series:
    return _sub(ema(src, fast), ema(src, slow))


def macd_signal(src: Series, fast: int, slow: int, signal: int) -> Series:
    return ema(macd(src, fast, slow), signal)


def stddev(src: Series, n: int) -> Series:
    def pop(w: list) -> float:
        mean = sum(w) / n
        return math.sqrt(sum([(x - mean) ** 2 for x in w]) / n)

    return _runs(src, n, pop)


def _band(src: Series, n: int, k: float, sign: float) -> Series:
    mid, dev = sma(src, n), stddev(src, n)
    return [None if m is None or d is None else m + sign * k * d for m, d in zip(mid, dev)]


def bb_upper(src: Series, n: int, k: float) -> Series:
    return _band(src, n, k, 1.0)


def bb_lower(src: Series, n: int, k: float) -> Series:
    return _band(src, n, k, -1.0)


def _true_range(high: Series, low: Series, close: Series) -> Series:
    out: Series = [None] * len(close)
    for i in range(len(close)):
        h, l = high[i], low[i]
        if h is None or l is None:
            continue
        if i == 0:
            out[i] = h - l
        elif close[i - 1] is not None:
            pc = close[i - 1]
            out[i] = max(h - l, abs(h - pc), abs(l - pc))
    return out


def atr(high: Series, low: Series, close: Series, n: int) -> Series:
    return _wilder(_true_range(high, low, close), n)


def roc(src: Series, n: int) -> Series:
    out: Series = [None] * len(src)
    for i in range(n, len(src)):
        now, then = src[i], src[i - n]
        if now is not None and then is not None and then != 0:
            out[i] = (now / then - 1.0) * 100.0
    return out


def highest(src: Series, n: int) -> Series:
    return _runs(src, n, max)


def lowest(src: Series, n: int) -> Series:
    return _runs(src, n, min)


def prev(src: Series, n: int = 1) -> Series:
    return [None] * min(n, len(src)) + list(src[:max(len(src) - n, 0)])


def _cross(a: Series, b: Series, above: bool) -> Series:
    out: Series = [None] * len(a)
    for i in range(1, len(a)):
        quad = (a[i], b[i], a[i - 1], b[i - 1])
        if None in quad:
            continue
        now_a, now_b, was_a, was_b = quad
        out[i] = (now_a > now_b and was_a <= was_b) if above else (now_a < now_b and was_a >= was_b)
    return out


def cross_above(a: Series, b: Series) -> Series:
    return _cross(a, b, True)


def cross_below(a: Series, b: Series) -> Series:
    return _cross(a, b, False)
