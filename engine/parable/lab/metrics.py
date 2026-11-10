import math
import statistics

from .consts import SECONDS_PER_YEAR
from .numeric import round_floats


def _returns(equity: list[float]) -> list[float]:
    return [b / a - 1.0 if a > 0 else 0.0 for a, b in zip(equity, equity[1:])]


def _max_drawdown(equity: list[float]) -> float:
    peak, worst = equity[0], 0.0
    for value in equity:
        peak = max(peak, value)
        if peak > 0:
            worst = max(worst, (peak - value) / peak)
    return worst * 100.0


def _stdev(values: list[float]) -> float:
    return statistics.stdev(values) if len(values) > 1 else 0.0


def _risk(returns: list[float], per_year: float) -> dict:
    sd = _stdev(returns)
    mean = sum(returns) / len(returns) if returns else 0.0
    downside = math.sqrt(sum(min(r, 0.0) ** 2 for r in returns) / len(returns)) if returns else 0.0
    root = math.sqrt(per_year)
    return {
        "volatility_pct": sd * root * 100.0,
        "sharpe": mean / sd * root if sd > 0 else 0.0,
        "sortino": mean / downside * root if downside > 0 else 0.0,
    }


def _cagr(start: float, final: float, years: float) -> float | None:
    if years < 0.25:
        return None
    ratio = final / start
    if ratio <= 0:
        return -100.0
    return (ratio ** (1.0 / years) - 1.0) * 100.0


def _trade_stats(trades: list[dict], interval_s: float) -> dict:
    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] < 0]
    gross_win = sum(t["pnl"] for t in wins)
    gross_loss = -sum(t["pnl"] for t in losses)
    count = len(trades)
    held = sum(t["bars_held"] for t in trades) / count if count else 0.0
    rets = [t["return_pct"] for t in trades]
    return {
        "trades": count,
        "win_rate_pct": len(wins) / count * 100.0 if count else 0.0,
        "profit_factor": gross_win / gross_loss if losses else None,
        "avg_win_pct": sum(t["return_pct"] for t in wins) / len(wins) if wins else 0.0,
        "avg_loss_pct": sum(t["return_pct"] for t in losses) / len(losses) if losses else 0.0,
        "best_trade_pct": max(rets) if rets else 0.0,
        "worst_trade_pct": min(rets) if rets else 0.0,
        "avg_hold_bars": held,
        "avg_hold_s": held * interval_s,
        "fees_paid": sum(t["fees"] for t in trades),
    }


def compute_metrics(times: list[float], equity: list[float], closes: list[float], trades: list[dict],
                    interval_s: float, start_cash: float, bars_in_position: int) -> dict:
    final = equity[-1]
    total = (final / start_cash - 1.0) * 100.0
    bench = (closes[-1] / closes[0] - 1.0) * 100.0 if closes[0] else 0.0
    years = (times[-1] - times[0]) / SECONDS_PER_YEAR
    out = {
        "total_return_pct": total,
        "benchmark_return_pct": bench,
        "excess_return_pct": total - bench,
        "cagr_pct": _cagr(start_cash, final, years),
        "max_drawdown_pct": _max_drawdown(equity),
    }
    out.update(_risk(_returns(equity), SECONDS_PER_YEAR / interval_s))
    out.update(_trade_stats(trades, interval_s))
    out.update({
        "exposure_pct": bars_in_position / len(equity) * 100.0,
        "start_cash": start_cash,
        "final_equity": final,
    })
    return round_floats(out)
