import math

import pytest

from parable.lab import indicators as ind

SRC = [10.0, 12.0, 11.0, 13.0, 15.0, 14.0]


def close_to(actual, expected):
    assert len(actual) == len(expected)
    for a, e in zip(actual, expected):
        if e is None:
            assert a is None
        else:
            assert a == pytest.approx(e, abs=1e-6)


def test_sma():
    close_to(ind.sma(SRC, 3), [None, None, 11, 12, 13, 14])
    close_to(ind.sma(SRC, 1), SRC)
    close_to(ind.sma(SRC, 6), [None] * 5 + [sum(SRC) / 6])
    close_to(ind.sma(SRC, 7), [None] * 6)


def test_ema():
    close_to(ind.ema(SRC, 3), [None, None, 11, 12, 13.5, 13.75])
    close_to(ind.ema(SRC, 1), SRC)


def test_rsi():
    close_to(ind.rsi(SRC, 3), [None, None, None, 80, 87.5, 100 - 100 / (1 + 1.037037037 / 0.481481481)])
    up = ind.rsi([1.0, 2, 3, 4, 5, 6], 3)
    close_to(up, [None, None, None, 100, 100, 100])
    down = ind.rsi([6.0, 5, 4, 3, 2, 1], 3)
    close_to(down, [None, None, None, 0, 0, 0])
    close_to(ind.rsi([5.0] * 6, 3), [None, None, None, 50, 50, 50])


def test_rsi_range():
    values = [v for v in ind.rsi([math.sin(i) * 5 + 50 for i in range(80)], 14) if v is not None]
    assert values and all(0 <= v <= 100 for v in values)


def test_macd_and_signal():
    close_to(ind.macd(SRC, 2, 3), [None, None, 0, 1 / 3, 0.611111111, 0.287037037])
    close_to(ind.macd_signal(SRC, 2, 3, 2), [None, None, None, 1 / 6, 0.462962963, 0.345679012])


def test_bollinger():
    sd = math.sqrt(2 / 3)
    close_to(ind.stddev(SRC, 3)[:3], [None, None, sd])
    upper, lower = ind.bb_upper(SRC, 3, 2), ind.bb_lower(SRC, 3, 2)
    assert upper[2] == pytest.approx(11 + 2 * sd) and lower[2] == pytest.approx(11 - 2 * sd)
    assert upper[:2] == [None, None] and lower[:2] == [None, None]
    close_to(ind.bb_upper(SRC, 3, 0), ind.sma(SRC, 3))


def test_stddev_population_not_sample():
    assert ind.stddev([1.0, 3.0], 2)[1] == pytest.approx(1.0)
    assert ind.stddev([4.0, 4.0, 4.0], 3)[2] == 0.0


def test_atr():
    high = [12.0, 13, 14, 13, 15]
    low = [10.0, 11, 12, 11, 12]
    close = [11.0, 12, 13, 12, 14]
    close_to(ind.atr(high, low, close, 3), [None, None, 2, 2, 7 / 3])
    close_to(ind.atr(high, low, close, 1), [2, 2, 2, 2, 3])


def test_atr_uses_gaps():
    out = ind.atr([10.0, 20.0], [9.0, 19.0], [9.5, 19.5], 1)
    assert out[1] == pytest.approx(10.5)


def test_roc():
    close_to(ind.roc(SRC, 3), [None, None, None, 30, 25, (14 / 11 - 1) * 100])
    assert ind.roc([0.0, 1.0, 2.0], 1) == [None, None, 1.0 * 100.0]


def test_highest_lowest():
    close_to(ind.highest(SRC, 3), [None, None, 12, 13, 15, 15])
    close_to(ind.lowest(SRC, 3), [None, None, 10, 11, 11, 13])


def test_prev():
    close_to(ind.prev(SRC, 2), [None, None, 10, 12, 11, 13])
    close_to(ind.prev(SRC), [None, 10, 12, 11, 13, 15])
    assert ind.prev([1.0, 2.0], 5) == [None, None]


def test_cross():
    a = [1.0, 2, 3, 2, 3]
    b = [2.0] * 5
    assert ind.cross_above(a, b) == [None, False, True, False, True]
    assert ind.cross_below(a, b) == [None, False, False, False, False]
    assert ind.cross_below([3.0, 1.0], [2.0, 2.0]) == [None, True]
    assert ind.cross_above([2.0, 3.0], [2.0, 2.0]) == [None, True]


def test_none_gaps_reset_windows():
    close_to(ind.sma([1.0, 2, None, 4, 5, 6], 2), [None, 1.5, None, None, 4.5, 5.5])
    close_to(ind.highest([1.0, None, 3, 2], 2), [None, None, None, 3])
    assert ind.cross_above([None, 1.0, 3.0], [1.0, 2.0, 2.0]) == [None, None, True]
    close_to(ind.roc([1.0, None, 2.0, 4.0], 1), [None, None, None, 100])


def test_warmup_relative_to_first_value():
    close_to(ind.sma([None, None, 1.0, 2, 3], 2), [None, None, None, 1.5, 2.5])
    close_to(ind.ema([None, 1.0, 2, 3, 4], 2), [None, None, 1.5, 2.5, 3.5])
    out = ind.rsi([None, 1.0, 2, 3, 2, 3], 2)
    assert out[:3] == [None] * 3 and out[3] is not None


def test_ema_restarts_after_gap():
    out = ind.ema([1.0, 2, 3, None, 10, 20, 30], 2)
    close_to(out, [None, 1.5, 2.5, None, None, 15, 25])


@pytest.mark.parametrize("fn,args,first", [
    (ind.sma, (5,), 4), (ind.ema, (5,), 4), (ind.rsi, (5,), 5), (ind.stddev, (5,), 4),
    (ind.highest, (5,), 4), (ind.lowest, (5,), 4), (ind.roc, (5,), 5), (ind.prev, (5,), 5),
    (ind.bb_upper, (5, 2.0), 4), (ind.bb_lower, (5, 2.0), 4),
])
def test_first_valid_index(fn, args, first):
    data = [100 + math.sin(i) * 3 + i * 0.1 for i in range(30)]
    out = fn(data, *args)
    assert len(out) == 30
    assert all(v is None for v in out[:first]) and out[first] is not None


def test_pure_no_mutation_and_same_length():
    src = [1.0, 2.0, None, 4.0, 5.0]
    snapshot = list(src)
    for fn in (ind.sma, ind.ema, ind.rsi, ind.stddev, ind.highest, ind.lowest, ind.roc, ind.prev):
        assert len(fn(src, 2)) == 5
    assert src == snapshot
    assert ind.sma([], 3) == [] and ind.cross_above([], []) == []
