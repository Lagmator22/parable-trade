import time

import pytest

from agents_support import spec_dict
from parable.errors import LabError
from parable.lab import optimize as opt
from parable.lab.backtest import run_backtest
from parable.lab.consts import MAX_BARS
from parable.lab.formula import FormulaError, evaluate, parse, synthetic_columns
from parable.lab.spec import SpecError, parse_spec, param_count
from lab_support import make_bars

HEAVY = "+".join(["stddev(close,500)"] * 9)


def heavy_spec() -> dict:
    spec = spec_dict()
    spec["params"] = {}
    spec["entry"] = f"close > ({HEAVY})"
    spec["exit"] = ""
    return spec


def test_hostile_spec_is_rejected_at_validation():
    with pytest.raises(SpecError) as rejected:
        parse_spec(heavy_spec())
    assert "expensive" in str(rejected.value)


def test_runtime_budget_rejects_a_hostile_formula_on_many_bars():
    columns = synthetic_columns(20_000)
    start = time.monotonic()
    with pytest.raises(FormulaError):
        evaluate(parse(f"close > ({HEAVY})"), columns, {})
    assert time.monotonic() - start < 2


def test_allowed_formula_on_the_largest_input_stays_fast():
    columns = synthetic_columns(MAX_BARS)
    start = time.monotonic()
    evaluate(parse("close > sma(close, 200) and rsi(close, 14) < 70 and close > bb_lower(close, 100, 2)"), columns, {})
    assert time.monotonic() - start < 3


def test_rolling_indicators_are_linear_time():
    columns = synthetic_columns(MAX_BARS)
    start = time.monotonic()
    evaluate(parse("stddev(close, 500) + sma(close, 500) + highest(high, 500) - lowest(low, 500)"), columns, {})
    assert time.monotonic() - start < 1.5


def test_optimize_stops_at_its_deadline(monkeypatch):
    monkeypatch.setattr(opt, "DEADLINE_S", -1.0)
    spec = parse_spec(spec_dict())
    with pytest.raises(LabError) as stopped:
        opt.optimize(spec, make_bars(400))
    assert stopped.value.code == "too_slow"


def test_huge_step_range_does_not_overflow():
    assert param_count(-1e308, 1e308, 1e-300) > 50
