import json
import math
import statistics

import pytest

from parable.lab.consts import SECONDS_PER_YEAR
from parable.lab.metrics import compute_metrics

DAY = 86400.0


def trade(pnl, ret, held, fees=0.5):
    return {"pnl": pnl, "return_pct": ret, "bars_held": held, "fees": fees}


def tiny():
    times = [0.0, DAY, 2 * DAY, 3 * DAY]
    equity = [100.0, 110.0, 99.0, 121.0]
    closes = [10.0, 11.0, 10.0, 12.0]
    trades = [trade(10, 10, 2), trade(-5, -5, 1), trade(20, 20, 3)]
    return compute_metrics(times, equity, closes, trades, DAY, 100.0, 3)


def test_keys_exact():
    assert set(tiny()) == {
        "total_return_pct", "benchmark_return_pct", "excess_return_pct", "cagr_pct", "max_drawdown_pct",
        "volatility_pct", "sharpe", "sortino", "trades", "win_rate_pct", "profit_factor", "avg_win_pct",
        "avg_loss_pct", "best_trade_pct", "worst_trade_pct", "exposure_pct", "avg_hold_bars", "avg_hold_s",
        "fees_paid", "start_cash", "final_equity",
    }


def test_return_family():
    m = tiny()
    assert m["total_return_pct"] == 21.0
    assert m["benchmark_return_pct"] == 20.0
    assert m["excess_return_pct"] == 1.0
    assert m["final_equity"] == 121.0 and m["start_cash"] == 100.0
    assert m["cagr_pct"] is None


def test_drawdown():
    assert tiny()["max_drawdown_pct"] == pytest.approx(10.0)


def test_risk_formulas():
    returns = [0.1, 99 / 110 - 1, 121 / 99 - 1]
    per_year = SECONDS_PER_YEAR / DAY
    sd = statistics.stdev(returns)
    mean = sum(returns) / 3
    downside = math.sqrt(sum(min(r, 0) ** 2 for r in returns) / 3)
    m = tiny()
    assert m["volatility_pct"] == pytest.approx(sd * math.sqrt(per_year) * 100, abs=1e-5)
    assert m["sharpe"] == pytest.approx(mean / sd * math.sqrt(per_year), abs=1e-5)
    assert m["sortino"] == pytest.approx(mean / downside * math.sqrt(per_year), abs=1e-5)


def test_trade_stats():
    m = tiny()
    assert m["trades"] == 3
    assert m["win_rate_pct"] == pytest.approx(66.666667)
    assert m["profit_factor"] == 6.0
    assert m["avg_win_pct"] == 15.0 and m["avg_loss_pct"] == -5.0
    assert m["best_trade_pct"] == 20.0 and m["worst_trade_pct"] == -5.0
    assert m["avg_hold_bars"] == 2.0 and m["avg_hold_s"] == 2 * DAY
    assert m["fees_paid"] == 1.5
    assert m["exposure_pct"] == 75.0


def test_cagr():
    one = compute_metrics([0.0, SECONDS_PER_YEAR], [100.0, 121.0], [1.0, 1.0], [], 3600, 100.0, 0)
    assert one["cagr_pct"] == pytest.approx(21.0)
    two = compute_metrics([0.0, 2 * SECONDS_PER_YEAR], [100.0, 121.0], [1.0, 1.0], [], 3600, 100.0, 0)
    assert two["cagr_pct"] == pytest.approx(10.0)
    short = compute_metrics([0.0, 0.24 * SECONDS_PER_YEAR], [100.0, 121.0], [1.0, 1.0], [], 3600, 100.0, 0)
    assert short["cagr_pct"] is None
    edge = compute_metrics([0.0, 0.25 * SECONDS_PER_YEAR], [100.0, 121.0], [1.0, 1.0], [], 3600, 100.0, 0)
    assert edge["cagr_pct"] is not None
    wiped = compute_metrics([0.0, SECONDS_PER_YEAR], [100.0, 0.0], [1.0, 1.0], [], 3600, 100.0, 0)
    assert wiped["cagr_pct"] == -100.0


def test_zero_trades():
    m = compute_metrics([0.0, DAY, 2 * DAY], [100.0, 100.0, 100.0], [5.0, 5.0, 5.0], [], DAY, 100.0, 0)
    assert m["trades"] == 0 and m["profit_factor"] is None
    for key in ("win_rate_pct", "avg_win_pct", "avg_loss_pct", "best_trade_pct", "worst_trade_pct",
                "avg_hold_bars", "avg_hold_s", "fees_paid", "sharpe", "sortino", "volatility_pct",
                "max_drawdown_pct", "exposure_pct", "total_return_pct"):
        assert m[key] == 0.0


def test_profit_factor_null_without_losses_and_no_negative_zero():
    m = compute_metrics([0.0, DAY], [100.0, 110.0], [1.0, 1.0], [trade(10, 10, 1)], DAY, 100.0, 1)
    assert m["profit_factor"] is None
    assert m["avg_loss_pct"] == 0.0 and str(m["avg_loss_pct"]) == "0.0"
    json.dumps(m, allow_nan=False)


def test_two_bars_and_single_return_edge():
    m = compute_metrics([0.0, DAY], [100.0, 90.0], [1.0, 1.0], [], DAY, 100.0, 0)
    assert m["volatility_pct"] == 0.0 and m["sharpe"] == 0.0
    assert m["sortino"] < 0 and m["max_drawdown_pct"] == pytest.approx(10.0)


def test_zero_close_benchmark_safe():
    m = compute_metrics([0.0, DAY], [100.0, 100.0], [0.0, 1.0], [], DAY, 100.0, 0)
    assert m["benchmark_return_pct"] == 0.0


def test_rounded_to_six():
    m = compute_metrics([0.0, DAY, 2 * DAY], [100.0, 100.3333333333, 100.7777777], [1.0, 1.0, 1.0], [], DAY, 100.0, 0)
    assert m["final_equity"] == 100.777778
