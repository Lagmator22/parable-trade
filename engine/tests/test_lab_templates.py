import pytest

from lab_data import synthetic_bars
from parable.errors import LabError
from parable.lab.backtest import run_backtest
from parable.lab.spec import spec_hash, validate_spec
from parable.lab.templates import TEMPLATES, list_templates, template_spec

IDS = ["trend", "dip", "mean_revert", "breakout", "rsi", "macd", "bollinger"]


def test_ids_and_listing():
    assert list(TEMPLATES) == IDS
    listing = list_templates()
    assert [t["id"] for t in listing] == IDS
    for item in listing:
        assert set(item) == {"id", "label", "blurb", "family"}
        assert all(item.values())
    listing[0]["label"] = "mutated"
    assert TEMPLATES["trend"]["label"] != "mutated"


@pytest.mark.parametrize("template_id", IDS)
def test_template_validates_and_is_tunable(template_id):
    spec = template_spec(template_id, "sample:BTCUSDT", "1h")
    validate_spec(spec)
    assert spec.built_by == f"template:{template_id}"
    assert len(spec.params) >= 2
    assert spec.stop_loss_pct > 0
    assert spec.symbol == "sample:BTCUSDT" and spec.interval == "1h"


@pytest.mark.parametrize("template_id", IDS)
def test_template_backtests_on_synthetic_bars(template_id):
    spec = template_spec(template_id, "sample:BTCUSDT", "1h")
    result = run_backtest(spec, synthetic_bars(900))
    assert result["metrics"]["start_cash"] == 10_000.0
    assert result["spec_hash"] == spec_hash(spec)
    again = run_backtest(spec, synthetic_bars(900))
    assert again["result_hash"] == result["result_hash"]


def test_some_template_trades():
    counts = [run_backtest(template_spec(t, "s:x", "1h"), synthetic_bars(900))["metrics"]["trades"] for t in IDS]
    assert sum(1 for c in counts if c > 0) >= 4


def test_unknown_template_and_bad_interval():
    with pytest.raises(LabError):
        template_spec("nope", "s:x", "1h")
    with pytest.raises(Exception):
        template_spec("trend", "s:x", "7m")


def test_specs_are_independent():
    a = template_spec("trend", "s:x", "1h")
    a.params["fast"].value = 99
    assert template_spec("trend", "s:x", "1h").params["fast"].value == 10
