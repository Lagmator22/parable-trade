import pytest

from lab_data import flat_bars, synthetic_bars
from parable.lab.signals import Position, closed_bars, decide, signal_series, stop_reason
from parable.models import ParamSpec, StrategySpec


def make(**kw):
    base = dict(symbol="s:x", interval="1h", entry="close > 100", exit="close < 100")
    base.update(kw)
    return StrategySpec(**base)


def bars_with_last(close, n=40):
    bars = flat_bars(n, 100.0)
    bars[-1] = [bars[-1][0], 100.0, max(100.0, close), min(100.0, close), close, 10.0]
    return bars


def test_decide_flat_buy_and_hold():
    spec = make()
    assert decide(spec, bars_with_last(105), None).action == "buy"
    assert decide(spec, bars_with_last(99), None).action == "hold"
    assert decide(spec, flat_bars(40), None).action == "hold"


def test_decide_long_sell_and_hold():
    spec = make()
    pos = Position(100.0, 0.0, 100.0)
    assert decide(spec, bars_with_last(95), pos).action == "sell"
    assert decide(spec, bars_with_last(105), pos).action == "hold"


def test_decide_ignores_entry_when_long_and_exit_when_flat():
    spec = make()
    assert decide(spec, bars_with_last(95), None).action == "hold"
    assert decide(spec, bars_with_last(105), Position(100.0, 0.0, 100.0)).action == "hold"


def test_decide_empty_exit_never_sells():
    spec = make(exit="")
    assert decide(spec, bars_with_last(50), Position(100.0, 0.0, 100.0)).action == "hold"


def test_decide_empty_bars():
    assert decide(make(), [], None).action == "hold"


def test_no_signal_before_warmup_even_for_negations():
    spec = make(entry="not (close > sma(close, 10))", exit="")
    bars = flat_bars(40, 100.0)
    entry, _ = signal_series(spec, bars)
    assert not any(entry[:9]) and entry[9] is True


def test_signal_series_params_override():
    spec = make(entry="close > sma(close, n)", exit="", params={"n": ParamSpec(value=5, min=2, max=20, step=1)})
    bars = synthetic_bars(100)
    a, _ = signal_series(spec, bars)
    b, _ = signal_series(spec, bars, {"n": 20})
    assert a != b and not any(b[:19])


def test_decide_matches_series_on_every_prefix():
    spec = make(entry="cross_above(ema(close, 5), sma(close, 12))", exit="cross_below(ema(close, 5), sma(close, 12))")
    bars = synthetic_bars(150)
    entry, exit_ = signal_series(spec, bars)
    for k in (40, 77, 100, 150):
        assert decide(spec, bars[:k], None).action == ("buy" if entry[k - 1] else "hold")
        assert decide(spec, bars[:k], Position(1.0, 0.0, 1.0)).action == ("sell" if exit_[k - 1] else "hold")


def test_stop_levels():
    spec = make(stop_loss_pct=5, take_profit_pct=10)
    pos = Position(100.0, 0.0, 100.0)
    assert stop_reason(spec, pos, 100, 104, 96) is None
    assert stop_reason(spec, pos, 100, 104, 95) == ("stop", 95.0)
    assert stop_reason(spec, pos, 100, 111, 99) == ("take_profit", pytest.approx(110.0))


def test_gap_fills_at_open():
    spec = make(stop_loss_pct=5, take_profit_pct=10)
    pos = Position(100.0, 0.0, 100.0)
    assert stop_reason(spec, pos, 90, 92, 88) == ("stop", 90)
    assert stop_reason(spec, pos, 115, 120, 114) == ("take_profit", 115)


def test_stop_wins_over_target():
    spec = make(stop_loss_pct=5, take_profit_pct=10)
    pos = Position(100.0, 0.0, 100.0)
    assert stop_reason(spec, pos, 100, 120, 90) == ("stop", 95.0)


def test_trailing_uses_high_water():
    spec = make(trailing_stop_pct=10)
    pos = Position(100.0, 0.0, 150.0)
    assert stop_reason(spec, pos, 140, 141, 135) == ("trailing", 135.0)
    assert stop_reason(spec, pos, 140, 141, 136.5) is None
    assert stop_reason(spec, pos, 130, 131, 129) == ("trailing", 130)


def test_stop_and_trailing_pick_higher_level_ties_to_stop():
    spec = make(stop_loss_pct=10, trailing_stop_pct=10)
    assert stop_reason(spec, Position(100.0, 0.0, 100.0), 100, 100, 80)[0] == "stop"
    assert stop_reason(spec, Position(100.0, 0.0, 130.0), 125, 125, 80) == ("trailing", 117.0)


def test_no_stops_configured():
    assert stop_reason(make(), Position(100.0, 0.0, 100.0), 100, 100, 1) is None


def test_closed_bars_drops_open_bar():
    bars = [[0.0, 1, 1, 1, 1, 1], [3600.0, 1, 1, 1, 1, 1], [7200.0, 1, 1, 1, 1, 1]]
    assert closed_bars(bars, "1h", 7200.0) == bars[:2]
    assert closed_bars(bars, "1h", 10800.0) == bars
    assert closed_bars(bars, "1h", 7199.9) == bars[:1]
    assert closed_bars([], "1h", 1e12) == []
    assert closed_bars(bars, "1d", 1e12) == bars
    with pytest.raises(KeyError):
        closed_bars(bars, "7m", 1.0)
