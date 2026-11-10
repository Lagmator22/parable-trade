import pytest

from lab_data import columns_of, synthetic_bars
from parable.lab import formula
from parable.lab.formula import FORMULA_REFERENCE, FormulaError, evaluate, parse, referenced_params, warmup
from parable.models import ParamSpec, StrategySpec

COLS = columns_of(synthetic_bars(300))


def tree(leaves):
    if leaves == 1:
        return "a"
    half = leaves // 2
    return "(" + tree(half) + "+" + tree(leaves - half) + ")"


def run(text, params=None, cols=COLS):
    return evaluate(parse(text), cols, params or {})


HOSTILE = [
    "__import__('os').system('id')",
    "__import__",
    "close.real",
    "close[0]",
    "(lambda: 1)()",
    "[x for x in close]",
    "{1: 2}",
    "[1, 2]",
    "(1, 2)",
    "{1}",
    "10**10**10",
    "close ** close",
    "close ** 5",
    "close ** -5",
    "1 < close < 3",
    "True",
    "False and close > 1",
    "None",
    "'abc'",
    "f'{close}'",
    "1j",
    "b'x'",
    "close if close else 1",
    "(y := 3)",
    "sma(close, n=3)",
    "sma(*close)",
    "sma",
    "close.sma(3)",
    "eval('1')",
    "open('x')",
    "sma(close, 0)",
    "sma(close, 501)",
    "sma(close, 2.5)",
    "sma(close, close)",
    "sma(close, -3)",
    "sma(close)",
    "sma(close, 3, 4)",
    "prev(close, 0)",
    "atr(1, 2)",
    "close in close",
    "close is close",
    "close not in close",
    "await close",
    "close @ close",
    "close // 2",
    "close << 2",
    "~close",
    "close & 1",
    "1e999",
    "10**400",
    "",
    "   ",
    "close >",
    "x = 1",
    "1; 2",
    "close\nand\nopen",
    "sma(close, 2)(3)",
    "close and",
    "\x00",
]


@pytest.mark.parametrize("text", HOSTILE)
def test_hostile_rejected(text):
    with pytest.raises(FormulaError):
        parse(text)


def test_deep_nesting_rejected():
    with pytest.raises(FormulaError):
        parse("abs(" * 13 + "close" + ")" * 13)
    parse("abs(" * 10 + "close" + ")" * 10)
    with pytest.raises(FormulaError):
        parse("-" * 300 + "close")
    with pytest.raises(FormulaError):
        parse("(" * 250 + "close" + ")" * 250)


def test_long_text_and_node_limits():
    with pytest.raises(FormulaError):
        parse("close > 1 " + "and close > 1 " * 40)
    with pytest.raises(FormulaError):
        parse(tree(70))
    parse(tree(40))
    with pytest.raises(FormulaError):
        parse("close > " + "1" * 400)


def test_exponent_rules():
    assert run("2 ** 3 > 7", cols=COLS)[0] is True
    assert run("close ** 2 > 0")[5] is True
    assert run("close ** -1 > 0")[5] is True
    assert run("close ** 0.5 > 0")[5] is True
    with pytest.raises(FormulaError):
        parse("close ** 4.01")


def test_valid_grammar():
    for text in [
        "close > open and not close < 1 or volume >= 0",
        "-close < 0",
        "+close > 0",
        "(close - open) / close * 100 != 3",
        "close % 7 == 3",
        "min(close, open) <= max(close, open)",
        "abs(close - open) >= 0",
        "bb_upper(close, 20, -1.5) > 0",
        "bb_upper(close, 20, 2) > bb_lower(close, 20, 2)",
        "atr(14) > 0",
        "prev(close) < 1000",
        "  close > 1  ",
    ]:
        parse(text)


def test_param_names_and_resolution():
    expr = parse("sma(close, n) > close * (1 - pct / 100)")
    assert referenced_params(expr) == {"n", "pct"}
    assert referenced_params(parse("sma(close, 5) > close")) == set()
    result = evaluate(expr, COLS, {"n": 5, "pct": 1})
    assert result[3] is False and isinstance(result[10], bool)


def test_unknown_name_at_eval():
    with pytest.raises(FormulaError):
        parse("__import__ > 1")
    with pytest.raises(FormulaError):
        parse("__import__('os')")
    with pytest.raises(FormulaError):
        evaluate(parse("foo > 1"), COLS, {})
    with pytest.raises(FormulaError):
        evaluate(parse("sma(close, n) > 1"), COLS, {})


def test_param_period_out_of_range():
    for value in (0, 501, float("nan"), float("inf"), -3):
        with pytest.raises(FormulaError):
            evaluate(parse("sma(close, n) > 1"), COLS, {"n": value})


def test_param_period_rounded():
    a = evaluate(parse("sma(close, n)"), COLS, {"n": 4.6})
    b = evaluate(parse("sma(close, 5)"), COLS, {})
    assert a == b


def test_reserved_param_name_rejected():
    with pytest.raises(FormulaError):
        evaluate(parse("close > 1"), COLS, {"close": 3})
    with pytest.raises(FormulaError):
        evaluate(parse("close > 1"), COLS, {"sma": 3})
    with pytest.raises(FormulaError):
        evaluate(parse("n > 1"), COLS, {"n": True})


def test_division_and_modulo_by_zero_is_none():
    cols = columns_of(synthetic_bars(40))
    assert evaluate(parse("close / 0"), cols, {})[0] is None
    assert evaluate(parse("close % 0"), cols, {})[0] is None
    assert evaluate(parse("close / 0 > 1"), cols, {})[0] is False
    assert evaluate(parse("not (close / 0 > 1)"), cols, {})[0] is True
    assert evaluate(parse("close / z"), cols, {"z": 0})[3] is None
    assert evaluate(parse("(0 - close) ** 0.5"), cols, {})[3] is None


def test_overflow_gives_none_not_crash():
    huge = {"open": [1e300] * 40, "high": [1e300] * 40, "low": [1e300] * 40, "close": [1e300] * 40, "volume": [1.0] * 40}
    assert evaluate(parse("close ** 4"), huge, {})[0] is None
    assert evaluate(parse("close * close"), huge, {})[0] is None
    assert evaluate(parse("close * close < 1"), huge, {})[0] is False


def test_none_semantics():
    out = run("sma(close, 5) > 0")
    assert out[:4] == [False] * 4 and out[4] is True
    out = run("sma(close, 5) + 1")
    assert out[:4] == [None] * 4 and out[4] is not None
    out = run("close > 0 and sma(close, 5) > 0")
    assert out[3] is False and out[4] is True
    out = run("not sma(close, 5)")
    assert out[0] is True


def test_comparison_operators():
    cols = columns_of(synthetic_bars(40))
    for op, expected in (("<", False), ("<=", True), (">", False), (">=", True), ("==", True), ("!=", False)):
        assert evaluate(parse(f"close {op} close"), cols, {})[0] is expected


def test_scalar_formula_broadcasts():
    assert run("1 < 2")[:3] == [True] * 3
    assert len(run("5")) == 300


def test_step_budget():
    big = {k: [1.0] * 50_000 for k in ("open", "high", "low", "close", "volume")}
    expr = parse(tree(58) + " > 1")
    with pytest.raises(FormulaError):
        evaluate(expr, big, {"a": 1})
    small = {k: [1.0] * 1000 for k in ("open", "high", "low", "close", "volume")}
    assert evaluate(expr, small, {"a": 1})[0] is True


def test_bad_columns():
    with pytest.raises(FormulaError):
        evaluate(parse("close > 1"), {"close": [1.0]}, {})
    bad = dict(COLS, high=COLS["high"][:5])
    with pytest.raises(FormulaError):
        evaluate(parse("close > 1"), bad, {})


def test_warmup_matches_first_valid_index():
    cases = {
        "sma(close, 5)": 4,
        "ema(close, 5)": 4,
        "rsi(close, 5)": 5,
        "macd(close, 3, 6)": 5,
        "macd_signal(close, 3, 6, 4)": 8,
        "bb_upper(close, 5, 2)": 4,
        "bb_lower(close, 5, 2)": 4,
        "atr(5)": 4,
        "roc(close, 5)": 5,
        "stddev(close, 5)": 4,
        "highest(close, 5)": 4,
        "lowest(close, 5)": 4,
        "prev(close, 5)": 5,
        "prev(close)": 1,
        "sma(sma(close, 3), 4)": 5,
        "cross_above(sma(close, 3), sma(close, 5))": 5,
        "cross_below(close, sma(close, 5))": 5,
        "close - sma(close, 5) + ema(close, 3)": 4,
        "abs(close - sma(close, 5))": 4,
        "max(rsi(close, 5), sma(close, 7))": 6,
        "sma(close, n) * 2": 8,
    }
    for text, first in cases.items():
        expr = parse(text)
        values = evaluate(expr, COLS, {"n": 9})
        index = next(i for i, v in enumerate(values) if v is not None)
        assert index == first, text
        assert warmup(expr, {"n": 9}) == first, text


def test_warmup_of_compare_and_missing_param():
    assert warmup(parse("close > sma(close, 7)"), {}) == 6
    with pytest.raises(FormulaError):
        warmup(parse("close > sma(close, n)"), {})


def test_dry_run_ok_and_fail():
    spec = StrategySpec(symbol="x:y", interval="1h", entry="close > sma(close, n)",
                        params={"n": ParamSpec(value=5, min=2, max=9, step=1)})
    formula.dry_run(spec)
    bad = spec.model_copy(update={"entry": "close > sma(close, m)"})
    with pytest.raises(FormulaError):
        formula.dry_run(bad)
    bad = spec.model_copy(update={"exit": "foo > 1"})
    with pytest.raises(FormulaError):
        formula.dry_run(bad)


def test_dry_run_deterministic_columns():
    assert formula.synthetic_columns(300) == formula.synthetic_columns(300)
    assert len(formula.synthetic_columns(300)["close"]) == 300


def test_reference_text():
    assert "cross_above" in FORMULA_REFERENCE and "EXAMPLES" in FORMULA_REFERENCE
    for name in ("sma", "ema", "rsi", "macd_signal", "bb_lower", "atr", "roc", "stddev", "highest", "prev"):
        assert name in FORMULA_REFERENCE


def test_evaluation_never_mutates_columns():
    snapshot = {k: list(v) for k, v in COLS.items()}
    run("cross_above(ema(close, 5), sma(close, 8)) or rsi(close, 5) > 50")
    assert COLS == snapshot


def test_no_dynamic_execution_in_sources():
    import inspect

    from parable.lab import formula_eval

    for module in (formula, formula_eval):
        source = inspect.getsource(module)
        for token in ("eval(", "exec(", "compile(", "__import__", "getattr(node"):
            assert token not in source.replace("def evaluate(", "").replace("run_formula(", ""), token
