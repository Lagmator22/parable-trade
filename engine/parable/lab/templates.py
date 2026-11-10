from ..errors import LabError
from ..models import ParamSpec, StrategySpec
from .spec import validate_spec

_SMA_X = "cross_above(sma(close, fast), sma(close, slow))"


def _p(value: float, low: float, high: float, step: float) -> ParamSpec:
    return ParamSpec(value=value, min=low, max=high, step=step)


_DEFS = {
    "trend": {
        "label": "Trend follower", "family": "trend",
        "blurb": "Buys when a fast average crosses above a slow one and leaves when it crosses back.",
        "entry": _SMA_X, "exit": "cross_below(sma(close, fast), sma(close, slow))",
        "params": {"fast": _p(10, 5, 30, 5), "slow": _p(40, 30, 100, 10)}, "stop": 5.0,
    },
    "dip": {
        "label": "Dip buyer", "family": "dip",
        "blurb": "Buys a drop from the recent high and sells when price recovers above its average.",
        "entry": "close < highest(close, look) * (1 - drop / 100)", "exit": "close > sma(close, look)",
        "params": {"look": _p(20, 10, 40, 10), "drop": _p(5, 3, 9, 2)}, "stop": 8.0,
    },
    "mean_revert": {
        "label": "Mean reversion", "family": "reversion",
        "blurb": "Buys when price falls well below its average and sells when it returns to it.",
        "entry": "close < sma(close, n) - k * stddev(close, n)", "exit": "close >= sma(close, n)",
        "params": {"n": _p(20, 10, 40, 10), "k": _p(1.5, 1, 2.5, 0.5)}, "stop": 6.0,
    },
    "breakout": {
        "label": "Breakout", "family": "breakout",
        "blurb": "Buys a close above the prior high and leaves on a close under the prior low.",
        "entry": "close > prev(highest(close, n))", "exit": "close < prev(lowest(close, m))",
        "params": {"n": _p(20, 10, 40, 10), "m": _p(10, 5, 20, 5)}, "stop": 7.0,
    },
    "rsi": {
        "label": "RSI bounce", "family": "momentum",
        "blurb": "Buys when RSI climbs back above an oversold level and sells at an overbought level.",
        "entry": "cross_above(rsi(close, n), lo)", "exit": "cross_above(rsi(close, n), hi)",
        "params": {"n": _p(14, 7, 21, 7), "lo": _p(30, 20, 40, 5), "hi": _p(70, 60, 80, 5)}, "stop": 6.0,
    },
    "macd": {
        "label": "MACD crossover", "family": "momentum",
        "blurb": "Buys when MACD crosses above its signal line and sells when it crosses below.",
        "entry": "cross_above(macd(close, fast, slow), macd_signal(close, fast, slow, sig))",
        "exit": "cross_below(macd(close, fast, slow), macd_signal(close, fast, slow, sig))",
        "params": {"fast": _p(12, 8, 16, 2), "slow": _p(26, 20, 34, 2), "sig": _p(9, 5, 13, 2)}, "stop": 6.0,
    },
    "bollinger": {
        "label": "Bollinger breakout", "family": "volatility",
        "blurb": "Buys when price pushes through the upper band and leaves when it drops under the average.",
        "entry": "cross_above(close, bb_upper(close, n, k))", "exit": "close < sma(close, n)",
        "params": {"n": _p(20, 10, 40, 10), "k": _p(2, 1, 3, 0.5)}, "stop": 5.0,
    },
}
TEMPLATES = {
    key: {"id": key, "label": d["label"], "blurb": d["blurb"], "family": d["family"]}
    for key, d in _DEFS.items()
}


def list_templates() -> list[dict]:
    return [dict(t) for t in TEMPLATES.values()]


def template_spec(template_id: str, symbol: str, interval: str) -> StrategySpec:
    definition = _DEFS.get(template_id)
    if definition is None:
        raise LabError(404, "not_found", "unknown template")
    spec = StrategySpec(
        name=definition["label"], summary=definition["blurb"], symbol=symbol, interval=interval,
        built_by=f"template:{template_id}", params={k: v.model_copy() for k, v in definition["params"].items()},
        entry=definition["entry"], exit=definition["exit"], stop_loss_pct=definition["stop"],
    )
    validate_spec(spec)
    return spec
