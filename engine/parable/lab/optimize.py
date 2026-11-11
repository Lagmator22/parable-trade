import itertools
import math
import random
from typing import Callable

from ..models import StrategySpec
from .backtest import quick_metrics
from .consts import MAX_GRID, MIN_BARS, TRAIN_FRACTION
from .spec import param_count, spec_hash, validate_spec

Progress = Callable[[float, str], None] | None


def _values(low: float, step: float, count: int) -> list:
    whole = float(low).is_integer() and float(step).is_integer()
    out = [round(low + k * step, 6) for k in range(count)]
    return [int(v) for v in out] if whole else out


def grid_axes(spec: StrategySpec) -> tuple[list[str], list[list]]:
    names = list(spec.params)
    axes = [_values(p.min, p.step, param_count(p.min, p.max, p.step)) for p in spec.params.values()]
    return names, axes


def _decode(index: int, axes: list[list]) -> list:
    combo = []
    for axis in reversed(axes):
        index, pick = divmod(index, len(axis))
        combo.append(axis[pick])
    return combo[::-1]


def candidates(spec: StrategySpec) -> tuple[list[dict], int]:
    names, axes = grid_axes(spec)
    size = math.prod(len(a) for a in axes)
    if size <= MAX_GRID:
        return [dict(zip(names, combo)) for combo in itertools.product(*axes)], size
    rng = random.Random(int(spec_hash(spec)[:8], 16))
    picked: set[int] = set()
    while len(picked) < MAX_GRID:
        picked.add(rng.randrange(size))
    return [dict(zip(names, _decode(i, axes))) for i in sorted(picked)], size


def _score(metrics: dict) -> float:
    return metrics["total_return_pct"] - 0.5 * metrics["max_drawdown_pct"]


def _overfit(train: dict, test: dict) -> bool:
    return train["sharpe"] > 0 and (test["sharpe"] < 0.5 * train["sharpe"] or test["total_return_pct"] <= 0)


def _ranked(scored: list[tuple[dict, dict]]) -> list[int]:
    def key(i: int):
        metrics = scored[i][1]
        return (metrics["trades"] < 3, -_score(metrics), i)

    return sorted(range(len(scored)), key=key)


def optimize(spec: StrategySpec, bars: list, *, top_k: int = 5, progress: Progress = None,
             partial: Callable[[dict], None] | None = None) -> dict:
    validate_spec(spec)
    train_n = math.floor(len(bars) * TRAIN_FRACTION)
    train, test = bars[:train_n], bars[train_n:]
    if train_n < MIN_BARS or len(test) < MIN_BARS:
        raise ValueError(f"need at least {MIN_BARS} bars in both the train and test split")
    combos, size = candidates(spec)
    report = progress or (lambda fraction, message: None)
    scored = []
    for done, params in enumerate(combos):
        scored.append((params, quick_metrics(spec, train, params)))
        if done % 10 == 0:
            report(0.9 * done / len(combos), f"trained {done}/{len(combos)}")
            if partial:
                partial({"rows": [], "grid_size": size, "evaluated": done})
    order = _ranked(scored)[:max(1, top_k)]
    rows = []
    for rank, i in enumerate(order):
        params, train_metrics = scored[i]
        test_metrics = quick_metrics(spec, test, params)
        rows.append({"params": params, "train": train_metrics, "test": test_metrics,
                     "overfit": _overfit(train_metrics, test_metrics)})
        report(0.9 + 0.1 * (rank + 1) / len(order), "testing")
        if partial:
            partial({"rows": list(rows), "grid_size": size, "evaluated": len(combos)})
    base = {"train": quick_metrics(spec, train), "test": quick_metrics(spec, test)}
    return {"rows": rows, "grid_size": size, "evaluated": len(combos), "train_bars": len(train),
            "test_bars": len(test), "base": base}
