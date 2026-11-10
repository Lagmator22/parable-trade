import json
import pytest

from lab_data import flat_bars, make_bars, synthetic_bars
from parable.lab.backtest import data_hash, downsample, result_hash, round_floats, run_backtest
from parable.lab.consts import BACKTEST_CASH, CURVE_MAX, ENGINE_VERSION, MIN_BARS
from parable.lab.spec import spec_hash
from parable.lab.templates import template_spec
from parable.models import ParamSpec, StrategySpec

CASH = 10_000.0


def make(**kw):
    base = dict(symbol="s:x", interval="1h", entry="close > 100", exit="close < 100", fee_bps=0, slippage_bps=0)
    base.update(kw)
    return StrategySpec(**base)


def scenario(rows, pad=10, tail=20):
    flat = [(100.0, 100.0, 100.0, 100.0)] * pad
    return make_bars(flat + list(rows) + [(rows[-1][3],) * 4] * tail)


ENTRY_ROWS = [(100, 106, 99, 105), (106, 108, 105, 107)]


def test_next_bar_open_fill_and_exit():
    bars = scenario(ENTRY_ROWS + [(107, 109, 106, 95), (94, 95, 90, 92)])
    r = run_backtest(make(), bars)
    assert len(r["trades"]) == 1
    t = r["trades"][0]
    assert t["entry_price"] == 106.0 and t["exit_price"] == 94.0
    assert t["entry_t"] == bars[11][0] and t["exit_t"] == bars[13][0]
    assert t["qty"] == pytest.approx(CASH / 106, abs=1e-6)
    assert t["pnl"] == pytest.approx(CASH * 94 / 106 - CASH, abs=1e-4)
    assert t["bars_held"] == 2 and t["reason"] == "signal" and t["fees"] == 0
    assert r["metrics"]["final_equity"] == pytest.approx(CASH * 94 / 106, abs=1e-4)
    assert [m["side"] for m in r["markers"]] == ["buy", "sell"]
    assert r["markers"][0]["t"] == bars[11][0] and r["markers"][1]["text"] == "signal"


def test_equity_per_bar_is_cash_plus_marked_holdings():
    bars = scenario(ENTRY_ROWS + [(107, 109, 106, 95), (94, 95, 90, 92)])
    r = run_backtest(make(), bars)
    by_t = {row[0]: row[1] for row in r["curve"]}
    assert by_t[bars[10][0]] == CASH
    assert by_t[bars[11][0]] == pytest.approx(CASH / 106 * 107, abs=1e-4)
    assert by_t[bars[12][0]] == pytest.approx(CASH / 106 * 95, abs=1e-4)
    assert by_t[bars[13][0]] == pytest.approx(CASH * 94 / 106, abs=1e-4)


def test_last_bar_signal_ignored():
    rows = [(100, 100, 100, 100)] * 29 + [(100, 106, 99, 105)]
    r = run_backtest(make(), make_bars(rows))
    assert r["trades"] == [] and r["markers"] == []
    assert r["metrics"]["final_equity"] == CASH


def test_open_position_closes_at_last_close_with_end_reason():
    bars = make_bars([(100.0,) * 4] * 27 + [(100, 106, 99, 105), (106, 108, 105, 107), (107, 110, 106, 108)])
    r = run_backtest(make(), bars)
    t = r["trades"][0]
    assert t["reason"] == "end" and t["exit_t"] == bars[-1][0] and t["exit_price"] == 108.0


def test_fees_and_slippage_exact():
    bars = scenario(ENTRY_ROWS + [(107, 109, 106, 95), (94, 95, 90, 92)])
    r = run_backtest(make(fee_bps=10, slippage_bps=5), bars)
    t = r["trades"][0]
    buy = 106 * 1.0005
    qty = CASH / (buy * 1.001)
    entry_fee = qty * buy * 0.001
    sell = 94 * 0.9995
    exit_fee = qty * sell * 0.001
    assert t["entry_price"] == pytest.approx(buy, abs=1e-6) and t["exit_price"] == pytest.approx(sell, abs=1e-6)
    assert t["qty"] == pytest.approx(qty, abs=1e-6)
    assert t["fees"] == pytest.approx(entry_fee + exit_fee, abs=1e-5)
    pnl = qty * sell - exit_fee - (qty * buy + entry_fee)
    assert t["pnl"] == pytest.approx(pnl, abs=1e-4)
    assert t["return_pct"] == pytest.approx(pnl / (qty * buy + entry_fee) * 100, abs=1e-5)
    assert r["metrics"]["fees_paid"] == pytest.approx(entry_fee + exit_fee, abs=1e-5)
    assert r["metrics"]["final_equity"] == pytest.approx(CASH + pnl, abs=1e-4)


def test_size_pct_leaves_cash_idle():
    bars = scenario(ENTRY_ROWS + [(107, 109, 106, 95), (94, 95, 90, 92)])
    r = run_backtest(make(size_pct=50), bars)
    assert r["trades"][0]["qty"] == pytest.approx(5000 / 106, abs=1e-6)
    assert r["metrics"]["final_equity"] == pytest.approx(5000 + 5000 * 94 / 106, abs=1e-4)


def test_stop_loss_intrabar_and_on_fill_bar():
    bars = scenario([(100, 106, 99, 105), (106, 108, 100, 107)] + [(107, 107, 107, 107)])
    t = run_backtest(make(stop_loss_pct=5), bars)["trades"][0]
    assert t["reason"] == "stop" and t["exit_price"] == pytest.approx(106 * 0.95) and t["bars_held"] == 0
    bars = scenario(ENTRY_ROWS + [(107, 108, 100, 105)])
    t = run_backtest(make(stop_loss_pct=5), bars)["trades"][0]
    assert t["reason"] == "stop" and t["exit_price"] == pytest.approx(106 * 0.95) and t["bars_held"] == 1


def test_gap_down_fills_at_open():
    bars = scenario(ENTRY_ROWS + [(107, 108, 106, 107), (90, 92, 88, 91)])
    t = run_backtest(make(stop_loss_pct=5), bars)["trades"][0]
    assert t["reason"] == "stop" and t["exit_price"] == 90.0


def test_gap_up_take_profit_fills_at_open():
    bars = scenario(ENTRY_ROWS + [(107, 108, 106, 107), (125, 130, 124, 128)])
    t = run_backtest(make(take_profit_pct=10), bars)["trades"][0]
    assert t["reason"] == "take_profit" and t["exit_price"] == 125.0


def test_take_profit_at_level():
    bars = scenario(ENTRY_ROWS + [(107, 120, 106, 118)])
    t = run_backtest(make(take_profit_pct=10), bars)["trades"][0]
    assert t["reason"] == "take_profit" and t["exit_price"] == pytest.approx(106 * 1.1)


def test_stop_before_target_same_bar():
    bars = scenario(ENTRY_ROWS + [(107, 125, 95, 110)])
    t = run_backtest(make(stop_loss_pct=5, take_profit_pct=10), bars)["trades"][0]
    assert t["reason"] == "stop" and t["exit_price"] == pytest.approx(106 * 0.95)


def test_trailing_stop_follows_high_water():
    rows = ENTRY_ROWS + [(107, 120, 107, 119), (119, 119, 107, 108)]
    t = run_backtest(make(trailing_stop_pct=10), scenario(rows))["trades"][0]
    assert t["reason"] == "trailing" and t["exit_price"] == pytest.approx(120 * 0.9)


def test_trailing_not_triggered_by_same_bar_high():
    rows = ENTRY_ROWS + [(107, 140, 100, 139)]
    t = run_backtest(make(trailing_stop_pct=10), scenario(rows))["trades"][0]
    assert t["reason"] == "end"
    rows = ENTRY_ROWS + [(107, 140, 100, 139), (139, 139, 120, 125)]
    t = run_backtest(make(trailing_stop_pct=10), scenario(rows))["trades"][0]
    assert t["reason"] == "trailing" and t["exit_price"] == pytest.approx(126.0)


def test_stop_slippage_applies_to_sells():
    bars = scenario(ENTRY_ROWS + [(107, 108, 100, 105)])
    t = run_backtest(make(stop_loss_pct=5, slippage_bps=100), bars)["trades"][0]
    assert t["entry_price"] == pytest.approx(106 * 1.01)
    assert t["exit_price"] == pytest.approx(106 * 1.01 * 0.95 * 0.99)


def test_reentry_after_stop_needs_new_signal_and_next_bar():
    rows = ENTRY_ROWS + [(107, 108, 100, 105), (105, 106, 104, 105), (105, 106, 104, 105)]
    r = run_backtest(make(stop_loss_pct=5), scenario(rows))
    assert [t["reason"] for t in r["trades"]][0] == "stop"
    assert len(r["trades"]) >= 2
    assert r["trades"][1]["entry_t"] > r["trades"][0]["exit_t"]


def test_one_position_at_a_time():
    r = run_backtest(make(entry="close > 0", exit=""), synthetic_bars(100))
    assert len(r["trades"]) == 1 and r["trades"][0]["reason"] == "end"


def test_params_override_and_hash():
    spec = make(entry="close > sma(close, n)", exit="", params={"n": ParamSpec(value=5, min=2, max=30, step=1)})
    bars = synthetic_bars(300)
    a = run_backtest(spec, bars)
    b = run_backtest(spec, bars, params={"n": 20})
    assert a["spec_hash"] == spec_hash(spec) and b["spec_hash"] != a["spec_hash"]
    assert b["result_hash"] != a["result_hash"]
    assert spec.params["n"].value == 5


def test_result_shape_and_passthrough():
    bars = synthetic_bars(120)
    r = run_backtest(template_spec("trend", "s:x", "1h"), bars, symbol="binance:BTCUSDT", interval="1h",
                     quote="USDT", source_kind="sample", start_cash=5000.0)
    assert set(r) == {"metrics", "curve", "trades", "markers", "data", "quote", "start_cash", "spec_hash",
                      "engine_version", "result_hash"}
    assert r["data"] == {"symbol": "binance:BTCUSDT", "interval": "1h", "start": bars[0][0], "end": bars[-1][0],
                         "bars": 120, "data_hash": data_hash(bars), "source_kind": "sample", "quote": "USDT"}
    assert r["quote"] == "USDT" and r["start_cash"] == 5000.0 and r["engine_version"] == ENGINE_VERSION
    assert r["curve"][0][1] == 5000.0 and r["curve"][0][2] == 5000.0
    assert r["curve"][-1][2] == pytest.approx(5000 * bars[-1][4] / bars[0][4], abs=1e-5)


def test_defaults():
    r = run_backtest(make(), flat_bars(40))
    assert r["quote"] == "USD" and r["data"]["source_kind"] == "market" and r["start_cash"] == BACKTEST_CASH
    assert r["data"]["symbol"] == "s:x" and r["data"]["interval"] == "1h"


def test_min_bars():
    with pytest.raises(ValueError):
        run_backtest(make(), flat_bars(MIN_BARS - 1))
    run_backtest(make(), flat_bars(MIN_BARS))


def test_bad_interval_override():
    with pytest.raises(ValueError):
        run_backtest(make(), flat_bars(40), interval="7m")


def test_determinism_result_hash():
    for tid in ("trend", "rsi", "bollinger"):
        spec = template_spec(tid, "s:x", "1h")
        a = run_backtest(spec, synthetic_bars(500))
        b = run_backtest(spec, synthetic_bars(500))
        assert a["result_hash"] == b["result_hash"]
        assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
        assert result_hash(a) == a["result_hash"]


def test_hash_sensitivity_and_markers_excluded():
    spec = template_spec("trend", "s:x", "1h")
    a = run_backtest(spec, synthetic_bars(500))
    assert run_backtest(spec, synthetic_bars(500, seed=8))["result_hash"] != a["result_hash"]
    stripped = dict(a, markers=[])
    assert result_hash(stripped) == a["result_hash"]
    assert result_hash(dict(a, trades=[])) != a["result_hash"]


def test_curve_downsampled_but_metrics_full():
    bars = synthetic_bars(2000)
    r = run_backtest(template_spec("trend", "s:x", "1h"), bars)
    assert len(r["curve"]) == CURVE_MAX
    assert r["curve"][0][0] == bars[0][0] and r["curve"][-1][0] == bars[-1][0]
    assert r["data"]["bars"] == 2000


def test_json_safe_no_nan_no_negative_zero():
    r = run_backtest(template_spec("breakout", "s:x", "1h"), synthetic_bars(700))
    text = json.dumps(r, allow_nan=False)
    assert "-0.0," not in text and "NaN" not in text


def test_zero_trade_run():
    r = run_backtest(make(entry="close > 1e9"), synthetic_bars(100))
    assert r["trades"] == [] and r["metrics"]["trades"] == 0
    assert r["metrics"]["final_equity"] == CASH and r["metrics"]["profit_factor"] is None


def test_zero_close_bars_do_not_crash():
    rows = [(0.0, 0.0, 0.0, 0.0)] * 40
    r = run_backtest(make(entry="close >= 0", exit=""), make_bars(rows))
    assert r["trades"] == [] and r["metrics"]["final_equity"] == CASH


def test_data_hash_rounding_and_order():
    bars = synthetic_bars(40)
    assert data_hash(bars) == data_hash([[x + 1e-10 for x in b] for b in bars])
    assert data_hash(bars) != data_hash(bars[::-1])
    assert len(data_hash(bars)) == 64


def test_downsample():
    pts = list(range(1000))
    out = downsample(pts, 100)
    assert len(out) == 100 and out[0] == 0 and out[-1] == 999 and out == sorted(set(out))
    assert downsample(pts[:50], 100) == pts[:50]
    assert downsample(pts, 2) == [0, 999]
    assert downsample(pts, 1) == [0, 999]
    assert downsample([], 10) == []
    assert downsample(pts, 100) == downsample(pts, 100)


def test_round_floats():
    out = round_floats({"a": 1.23456789, "b": [float("nan"), float("inf"), -0.0, 1e-9, -1e-9], "c": (1, 2.5), "d": True,
                        "e": None, "f": {"g": 0.1234565}})
    assert out["a"] == 1.234568
    assert out["b"] == [None, None, 0.0, 0.0, 0.0]
    assert str(out["b"][2]) == "0.0" and str(out["b"][4]) == "0.0"
    assert out["c"] == [1, 2.5] and out["d"] is True and out["e"] is None
    assert out["f"]["g"] in (0.123456, 0.123457)
