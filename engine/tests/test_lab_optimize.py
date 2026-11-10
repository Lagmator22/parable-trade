import json

import pytest

from lab_data import synthetic_bars
from parable.lab import optimize as opt
from parable.lab.consts import MAX_GRID
from parable.lab.optimize import candidates, optimize
from parable.lab.spec import SpecError
from parable.lab.templates import template_spec
from parable.models import ParamSpec, StrategySpec


def make(params, entry="close > sma(close, n)", exit=""):
    return StrategySpec(symbol="s:x", interval="1h", entry=entry, exit=exit, params=params)


def p(value, low, high, step):
    return ParamSpec(value=value, min=low, max=high, step=step)


def metrics(trades=5, ret=10.0, dd=2.0, sharpe=1.0):
    return {"trades": trades, "total_return_pct": ret, "max_drawdown_pct": dd, "sharpe": sharpe}


def test_grid_inclusive_ints_and_floats():
    spec = make({"n": p(5, 2, 8, 2), "k": p(1.0, 0.5, 1.5, 0.5)}, "close > sma(close, n) * k")
    combos, size = candidates(spec)
    assert size == 12 and len(combos) == 12
    assert {c["n"] for c in combos} == {2, 4, 6, 8}
    assert all(isinstance(c["n"], int) for c in combos)
    assert {c["k"] for c in combos} == {0.5, 1.0, 1.5}
    assert all(isinstance(c["k"], float) for c in combos)
    assert combos[0] == {"n": 2, "k": 0.5} and combos[-1] == {"n": 8, "k": 1.5}


def test_grid_float_steps_rounded():
    spec = make({"k": p(0.3, 0.1, 0.7, 0.1)}, "close * k > 0")
    values = [c["k"] for c in candidates(spec)[0]]
    assert values == [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7]


def test_no_params_single_candidate():
    combos, size = candidates(make({}, "close > open"))
    assert combos == [{}] and size == 1


def test_grid_sampled_deterministically_over_limit():
    params = {name: p(10, 1, 20, 1) for name in ("a", "b", "c")}
    spec = make(params, "close > sma(close, a) and close > sma(close, b) and close > sma(close, c)")
    combos, size = candidates(spec)
    assert size == 8000 and len(combos) == MAX_GRID
    assert combos == candidates(spec)[0]
    assert len({tuple(c.values()) for c in combos}) == MAX_GRID
    assert all(1 <= v <= 20 for c in combos for v in c.values())
    other = candidates(spec.model_copy(update={"symbol": "s:y"}))[0]
    assert other != combos


def test_huge_grid_does_not_overflow():
    params = {f"p{i}": p(10, 1, 50, 1) for i in range(12)}
    entry = " and ".join(f"close > sma(close, p{i})" for i in range(12))
    combos, size = candidates(make(params, entry))
    assert size == 50 ** 12 and len(combos) == MAX_GRID


def test_split_and_test_uses_only_test_slice(monkeypatch):
    seen = []

    def fake(spec, bars, params=None, start_cash=10_000.0):
        seen.append((len(bars), bars[0][0], dict(params or {})))
        return metrics(ret=params["n"] if params else 0.0)

    monkeypatch.setattr(opt, "quick_metrics", fake)
    bars = synthetic_bars(200)
    out = optimize(make({"n": p(5, 2, 8, 2)}), bars, top_k=2)
    assert out["train_bars"] == 140 and out["test_bars"] == 60
    train_calls = [c for c in seen if c[0] == 140]
    test_calls = [c for c in seen if c[0] == 60]
    assert len(train_calls) == 4 + 1 and all(c[1] == bars[0][0] for c in train_calls)
    assert len(test_calls) == 2 + 1 and all(c[1] == bars[140][0] for c in test_calls)
    assert [r["params"]["n"] for r in out["rows"]] == [8, 6]


def test_split_floor():
    out = optimize(make({"n": p(5, 2, 8, 2)}), synthetic_bars(333), top_k=1)
    assert out["train_bars"] == 233 and out["test_bars"] == 100


def test_ranking_requires_three_trades_and_uses_score(monkeypatch):
    table = {
        1: metrics(trades=2, ret=500.0, dd=0.0),
        2: metrics(trades=3, ret=10.0, dd=0.0),
        3: metrics(trades=10, ret=30.0, dd=40.0),
        4: metrics(trades=4, ret=15.0, dd=2.0),
        5: metrics(trades=0, ret=0.0, dd=0.0),
    }
    monkeypatch.setattr(opt, "quick_metrics", lambda spec, bars, params=None, start_cash=0: table[params["n"]] if params else metrics())
    out = optimize(make({"n": p(1, 1, 5, 1)}), synthetic_bars(200), top_k=5)
    assert [r["params"]["n"] for r in out["rows"]] == [4, 2, 3, 1, 5]
    assert out["evaluated"] == 5 and out["grid_size"] == 5


def test_tie_break_is_grid_order(monkeypatch):
    monkeypatch.setattr(opt, "quick_metrics", lambda spec, bars, params=None, start_cash=0: metrics())
    out = optimize(make({"n": p(1, 1, 4, 1)}), synthetic_bars(200), top_k=4)
    assert [r["params"]["n"] for r in out["rows"]] == [1, 2, 3, 4]


def test_overfit_rule():
    assert opt._overfit(metrics(sharpe=2.0), metrics(sharpe=0.9, ret=5.0)) is True
    assert opt._overfit(metrics(sharpe=2.0), metrics(sharpe=1.0, ret=5.0)) is False
    assert opt._overfit(metrics(sharpe=2.0), metrics(sharpe=1.5, ret=0.0)) is True
    assert opt._overfit(metrics(sharpe=2.0), metrics(sharpe=1.5, ret=-1.0)) is True
    assert opt._overfit(metrics(sharpe=0.0), metrics(sharpe=-5.0, ret=-9.0)) is False
    assert opt._overfit(metrics(sharpe=-1.0), metrics(sharpe=-5.0, ret=-9.0)) is False


def test_overfit_flag_in_rows(monkeypatch):
    def fake(spec, bars, params=None, start_cash=0):
        if len(bars) == 140:
            return metrics(sharpe=2.0)
        return metrics(sharpe=0.1, ret=-1.0)

    monkeypatch.setattr(opt, "quick_metrics", fake)
    out = optimize(make({"n": p(5, 2, 8, 2)}), synthetic_bars(200), top_k=1)
    assert out["rows"][0]["overfit"] is True


def test_real_optimise_structure_and_determinism():
    spec = template_spec("trend", "s:x", "1h")
    bars = synthetic_bars(900)
    a = optimize(spec, bars, top_k=3)
    b = optimize(spec, bars, top_k=3)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    assert set(a) == {"rows", "grid_size", "evaluated", "train_bars", "test_bars", "base"}
    assert a["grid_size"] == 48 and a["evaluated"] == 48 and len(a["rows"]) == 3
    assert a["train_bars"] == 630 and a["test_bars"] == 270
    row = a["rows"][0]
    assert set(row) == {"params", "train", "test", "overfit"} and set(a["base"]) == {"train", "test"}
    assert set(row["params"]) == {"fast", "slow"} and isinstance(row["overfit"], bool)
    scores = [r["train"]["total_return_pct"] - 0.5 * r["train"]["max_drawdown_pct"] for r in a["rows"]]
    eligible = [(s, r) for s, r in zip(scores, a["rows"]) if r["train"]["trades"] >= 3]
    assert [s for s, _ in eligible] == sorted((s for s, _ in eligible), reverse=True)


def test_real_row_matches_direct_backtest():
    from parable.lab.backtest import run_backtest

    spec = template_spec("mean_revert", "s:x", "1h")
    bars = synthetic_bars(900)
    out = optimize(spec, bars, top_k=1)
    row = out["rows"][0]
    direct = run_backtest(spec, bars[:630], params=row["params"])["metrics"]
    assert direct == row["train"]
    assert run_backtest(spec, bars[630:], params=row["params"])["metrics"] == row["test"]


def test_top_k_bounds():
    spec = make({"n": p(5, 2, 6, 2)})
    bars = synthetic_bars(200)
    assert len(optimize(spec, bars, top_k=50)["rows"]) == 3
    assert len(optimize(spec, bars, top_k=0)["rows"]) == 1


def test_progress_callback_monotonic():
    calls = []
    optimize(template_spec("trend", "s:x", "1h"), synthetic_bars(400), top_k=2,
             progress=lambda fraction, message: calls.append((fraction, message)))
    fractions = [c[0] for c in calls]
    assert fractions and fractions == sorted(fractions) and 0 <= fractions[0] and fractions[-1] <= 1.0
    assert all(isinstance(c[1], str) for c in calls)


def test_too_few_bars_and_invalid_spec():
    spec = template_spec("trend", "s:x", "1h")
    with pytest.raises(ValueError):
        optimize(spec, synthetic_bars(90))
    optimize(spec, synthetic_bars(98), top_k=1)
    with pytest.raises(SpecError):
        optimize(spec.model_copy(update={"entry": "__import__('os')"}), synthetic_bars(200))


def test_large_optimise_completes_quickly():
    import time

    spec = make({"a": p(10, 2, 30, 1), "b": p(30, 5, 50, 1)}, "cross_above(ema(close, a), sma(close, b))",
                "cross_below(ema(close, a), sma(close, b))")
    start = time.time()
    out = optimize(spec, synthetic_bars(1000), top_k=5)
    assert out["evaluated"] == MAX_GRID and time.time() - start < 30
