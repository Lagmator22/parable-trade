import re

SERIES = ("open", "high", "low", "close", "volume")
FUNCS = {
    "sma": ("sp", 2), "ema": ("sp", 2), "rsi": ("sp", 2),
    "macd": ("spp", 3), "macd_signal": ("sppp", 4),
    "bb_upper": ("spf", 3), "bb_lower": ("spf", 3),
    "atr": ("p", 1), "roc": ("sp", 2), "stddev": ("sp", 2),
    "highest": ("sp", 2), "lowest": ("sp", 2), "prev": ("sp", 1),
    "cross_above": ("ss", 2), "cross_below": ("ss", 2),
    "abs": ("s", 1), "min": ("ss", 2), "max": ("ss", 2),
}
RESERVED = frozenset(SERIES) | frozenset(FUNCS)
NAME_RE = re.compile(r"^[a-z_][a-z0-9_]{0,23}$")
MAX_CONSTANT = 1e15


class FormulaError(ValueError):
    pass


FORMULA_REFERENCE = """FORMULA LANGUAGE (one expression, Python-like syntax, long-only strategy)
A formula is a single expression that is true or false on each closed bar. Entry is checked while flat, exit while holding.
Series names: open high low close volume. Parameter names: lowercase letters, digits, underscore, at most 24 chars, declared in the params object.
Operators: + - * / % ** (the exponent must be a plain number with abs <= 4), comparisons < <= > >= == != (only one per expression part, no chaining), and, or, not, parentheses, numbers.
Not allowed: attributes, indexing, lambdas, comprehensions, if-else, strings, booleans True/False, lists, keyword arguments, anything else.
Period arguments (n, fast, slow, signal, prev lag) must be a whole number literal or a bare parameter name, between 1 and 500. The multiplier k may be a decimal literal or a parameter name.
Division or modulo by zero gives no value, and any comparison with no value is false. Warm-up bars before an indicator is ready never trigger signals.
Limits: 400 characters, nesting depth 12, 120 nodes.
FUNCTIONS (each returns a series)
sma(src, n)                       simple moving average
ema(src, n)                       exponential moving average
rsi(src, n)                       Wilder RSI, 0 to 100
macd(src, fast, slow)             ema(fast) - ema(slow)
macd_signal(src, fast, slow, signal)  ema of macd with period signal
bb_upper(src, n, k)               sma + k * population standard deviation
bb_lower(src, n, k)               sma - k * population standard deviation
atr(n)                            Wilder average true range
roc(src, n)                       percent change over n bars
stddev(src, n)                    population standard deviation
highest(src, n) / lowest(src, n)  highest or lowest value including the current bar
prev(src, n)                      value n bars ago (prev(src) means 1 bar)
cross_above(a, b) / cross_below(a, b)  true on the bar where a crosses over or under b
abs(x), min(a, b), max(a, b)      elementwise
EXAMPLES
entry: cross_above(sma(close, fast), sma(close, slow))    exit: cross_below(sma(close, fast), sma(close, slow))
entry: rsi(close, n) < level and close > sma(close, 100)  exit: rsi(close, n) > 55
entry: close > prev(highest(close, n))                    exit: close < prev(lowest(close, 10))
"""
