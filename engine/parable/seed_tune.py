from parable.lab.backtest import run_backtest
from parable.lab.optimize import optimize
from parable.lab.templates import template_spec

MIN_TRADES = 3
TOP_K = 10


def tune(template: str, symbol: str, interval: str, bars: list, name: str):
    base = template_spec(template, symbol, interval).model_copy(update={"name": name[:60]})
    try:
        rows = optimize(base, bars, top_k=TOP_K)["rows"]
    except ValueError:
        rows = []
    usable = [row for row in rows if row["test"]["trades"] >= MIN_TRADES]
    if not usable:
        return base, False
    best = max(usable, key=lambda row: row["test"]["total_return_pct"] - 0.5 * row["test"]["max_drawdown_pct"])
    params = {key: base.params[key].model_copy(update={"value": float(value)}) for key, value in best["params"].items()}
    return base.model_copy(update={"params": params}), True


def score(metrics: dict) -> tuple:
    gain = metrics["total_return_pct"]
    beats = gain > metrics["benchmark_return_pct"]
    return (beats and gain > 0, beats, gain)


def best_candidate(candidates: list[tuple[str, str, str, list]], name: str) -> dict | None:
    best = None
    for template, symbol, interval, bars in candidates:
        strategy, tuned = tune(template, symbol, interval, bars, name)
        result = run_backtest(strategy, bars, symbol=symbol, interval=interval)
        key = score(result["metrics"])
        if best is None or key > best["key"]:
            best = {"key": key, "template": template, "symbol": symbol, "interval": interval, "bars": bars,
                    "strategy": strategy, "tuned": tuned}
    return best
