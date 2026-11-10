import json

import pytest

from parable import db
from parable.errors import LabError
from parable.lab.consts import MAX_PARAM_VALUES, MAX_PARAMS
from parable.lab.spec import (
    SpecError, canonical_spec, load_spec, parse_spec, required_bars, resolve_params,
    spec_hash, validate_spec, warmup_bars, with_params,
)
from parable.models import ParamSpec, StrategySpec


def make(**kw):
    base = dict(symbol="sample:BTCUSDT", interval="1h", entry="close > sma(close, n)", exit="",
                params={"n": ParamSpec(value=10, min=5, max=20, step=5)})
    base.update(kw)
    return StrategySpec(**base)


def errors_of(spec):
    with pytest.raises(SpecError) as info:
        validate_spec(spec)
    return info.value.errors


def test_valid_spec_passes():
    validate_spec(make())
    validate_spec(make(params={}, entry="close > open"))


def test_unknown_param_reference():
    errs = errors_of(make(entry="close > sma(close, m)"))
    assert any("unknown name 'm'" in e for e in errs)


def test_bad_interval_symbol():
    assert any("interval" in e for e in errors_of(make(interval="7m")))
    assert any("symbol" in e for e in errors_of(make(symbol="  ")))


def test_formula_errors_labelled():
    errs = errors_of(make(entry="__import__('os')", exit="close.real"))
    assert any(e.startswith("entry:") for e in errs) and any(e.startswith("exit:") for e in errs)


def test_param_range_and_values():
    errs = errors_of(make(params={"n": ParamSpec(value=30, min=5, max=20, step=5)}))
    assert any("min <= value <= max" in e for e in errs)
    wide = ParamSpec(value=10, min=1, max=MAX_PARAM_VALUES + 5, step=1)
    assert any("values" in e for e in errors_of(make(params={"n": wide})))
    ok = ParamSpec(value=10, min=1, max=MAX_PARAM_VALUES, step=1)
    validate_spec(make(params={"n": ok}))


def test_integer_use_requires_integral_value_and_range():
    errs = errors_of(make(params={"n": ParamSpec(value=10.5, min=5, max=20, step=1)}))
    assert any("period" in e for e in errs)
    errs = errors_of(make(params={"n": ParamSpec(value=10, min=0, max=20, step=1)}))
    assert any("period" in e for e in errs)
    errs = errors_of(make(params={"n": ParamSpec(value=10, min=5, max=600, step=50)}))
    assert any("period" in e for e in errs)
    validate_spec(make(entry="close > sma(close, 5) * k", params={"k": ParamSpec(value=0.97, min=0.9, max=1, step=0.01)}))


def test_param_name_rules():
    for bad in ("close", "sma", "Bad", "x" * 25, "1a", "a b"):
        errs = errors_of(make(entry="close > 1", params={bad: ParamSpec(value=1, min=0, max=2, step=1)}))
        assert any("invalid or reserved" in e for e in errs), bad


def test_param_count_limit():
    params = {f"p{i}": ParamSpec(value=1, min=0, max=2, step=1) for i in range(MAX_PARAMS + 1)}
    assert any("at most" in e for e in errors_of(make(entry="close > 1", params=params)))


def test_spec_size_limit():
    params = {f"p{i:02d}": ParamSpec(value=1, min=0, max=2, step=1) for i in range(12)}
    validate_spec(make(entry="close > 1", params=params))
    big = make(entry="close > 1", summary="x" * 300, name="y" * 60)
    validate_spec(big)
    assert any("larger" in e for e in errors_of(big.model_copy(update={"symbol": "s" * 9000})))


def test_dry_run_failure_reported():
    errs = errors_of(make(entry="sma(close, n) > 1", params={"n": ParamSpec(value=1, min=1, max=2, step=1)}).model_copy(
        update={"params": {"n": ParamSpec(value=1, min=1, max=2, step=1), "zero": ParamSpec(value=0, min=0, max=0, step=1)},
                "entry": "sma(close, n) > 1 and zero > 5 and close > nothing"}))
    assert errs


def test_parse_spec_from_dict_and_json():
    raw = {"symbol": "sample:BTCUSDT", "interval": "1h", "entry": "  close > open  "}
    spec = parse_spec(raw)
    assert spec.entry == "close > open"
    assert parse_spec(json.dumps(raw)) == spec


def test_parse_spec_failures():
    for raw in ("not json", "[1]", "42", {}, {"symbol": "x", "interval": "1h", "entry": ""},
                {"symbol": "x", "interval": "1h", "entry": "close > 1", "size_pct": 0},
                {"symbol": "x", "interval": "1h", "entry": "close > 1", "stop_loss_pct": 51},
                {"symbol": "x", "interval": "1h", "entry": "close > 1", "fee_bps": 500},
                {"symbol": "x", "interval": "9z", "entry": "close > 1"},
                {"symbol": "x", "interval": "1h", "entry": "1 < close < 3"},
                "x" * 40_000):
        with pytest.raises(SpecError) as info:
            parse_spec(raw)
        assert info.value.errors


def test_parse_spec_deep_json_does_not_crash():
    with pytest.raises(SpecError):
        parse_spec("[" * 5000)


def test_canonical_and_hash_ignore_cosmetics():
    a = make(name="One", summary="a", built_by="manual")
    b = make(name="Two", summary="b", built_by="gemini:x", entry="  close > sma(close, n)  ")
    assert spec_hash(a) == spec_hash(b)
    assert len(spec_hash(a)) == 64 and spec_hash(a) == spec_hash(a).lower()
    assert spec_hash(a) != spec_hash(make(size_pct=50))
    assert spec_hash(a) != spec_hash(make(symbol="sample:ETHUSDT"))
    canon = canonical_spec(b)
    assert canon["entry"] == "close > sma(close, n)" and canon["name"] == "Two"
    assert json.dumps(canon, sort_keys=True)


def test_hash_rounds_floats():
    a = make(fee_bps=10.0000001)
    assert spec_hash(a) == spec_hash(make(fee_bps=10.0))


def test_resolve_params():
    spec = make()
    assert resolve_params(spec) == {"n": 10.0}
    assert resolve_params(spec, {"n": 7}) == {"n": 7.0}
    with pytest.raises(SpecError):
        resolve_params(spec, {"zzz": 1})
    with pytest.raises(SpecError):
        resolve_params(spec, {"n": float("nan")})
    with pytest.raises(SpecError):
        resolve_params(spec, {"n": True})
    assert with_params(spec, {"n": 15}).params["n"].value == 15.0
    assert spec.params["n"].value == 10
    assert with_params(spec, None) is spec


def test_warmup_and_required_bars():
    spec = make()
    assert warmup_bars(spec) == 9
    assert warmup_bars(spec, {"n": 20}) == 19
    assert required_bars(spec) == 300
    big = make(entry="close > sma(close, 400)", params={})
    assert warmup_bars(big) == 399 and required_bars(big) == 1197
    both = make(entry="close > sma(close, 3)", exit="close < sma(close, 12)", params={})
    assert warmup_bars(both) == 11


def test_load_spec_roundtrip_and_missing():
    spec = make(name="Saved")
    db.execute(
        "INSERT INTO agent_versions (id, agent_id, n, name, summary, spec_json, spec_hash, steps_text, built_by, created_at)"
        " VALUES ('v_1', 'a_1', 1, 'Saved', '', ?, ?, '', 'manual', 1)",
        (json.dumps(canonical_spec(spec)), spec_hash(spec)),
    )
    assert load_spec("v_1") == spec
    with pytest.raises(LabError) as info:
        load_spec("v_missing")
    assert info.value.status == 404
