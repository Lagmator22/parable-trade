import json

from ..models import StrategySpec
from .consts import BACKTEST_CASH, CURVE_MAX, ENGINE_VERSION, INTERVAL_SECONDS, MIN_BARS
from .metrics import compute_metrics
from .numeric import canonical_json, round_floats, sha256_hex
from .signals import Position, signal_series, stop_reason
from .spec import spec_hash, with_params

__all__ = ["round_floats", "data_hash", "result_hash", "downsample", "run_backtest", "quick_metrics"]


def data_hash(bars: list) -> str:
    return sha256_hex(json.dumps([[float(round(x, 8)) for x in bar] for bar in bars], separators=(",", ":")))


def result_hash(result: dict) -> str:
    body = {k: v for k, v in result.items() if k not in ("markers", "result_hash")}
    return sha256_hex(canonical_json(body))


def downsample(points: list, limit: int) -> list:
    n = len(points)
    limit = max(limit, 2)
    if n <= limit:
        return list(points)
    return [points[round(i * (n - 1) / (limit - 1))] for i in range(limit)]


class _Sim:
    def __init__(self, spec: StrategySpec, start_cash: float) -> None:
        self.spec = spec
        self.cash = start_cash
        self.qty = 0.0
        self.pos: Position | None = None
        self.entry_index = 0
        self.entry_cost = 0.0
        self.entry_fee = 0.0
        self.trades: list[dict] = []
        self.markers: list[dict] = []

    def buy(self, i: int, t: float, price: float) -> bool:
        spec = self.spec
        fill = price * (1 + spec.slippage_bps / 1e4)
        if fill <= 0 or self.cash <= 0:
            return False
        fee_rate = spec.fee_bps / 1e4
        qty = self.cash * spec.size_pct / 100 / (fill * (1 + fee_rate))
        self.entry_fee = qty * fill * fee_rate
        self.entry_cost = qty * fill + self.entry_fee
        self.cash -= self.entry_cost
        self.qty = qty
        self.pos = Position(fill, t, fill)
        self.entry_index = i
        self.markers.append({"t": t, "side": "buy", "price": fill, "text": "entry"})
        return True

    def sell(self, i: int, t: float, price: float, reason: str) -> None:
        spec = self.spec
        fill = price * (1 - spec.slippage_bps / 1e4)
        gross = self.qty * fill
        exit_fee = gross * spec.fee_bps / 1e4
        proceeds = gross - exit_fee
        pnl = proceeds - self.entry_cost
        self.cash += proceeds
        self.trades.append({
            "entry_t": self.pos.entry_t, "exit_t": t, "entry_price": self.pos.entry_price,
            "exit_price": fill, "qty": self.qty, "pnl": pnl,
            "return_pct": pnl / self.entry_cost * 100 if self.entry_cost else 0.0,
            "bars_held": i - self.entry_index, "fees": self.entry_fee + exit_fee, "reason": reason,
        })
        self.markers.append({"t": t, "side": "sell", "price": fill, "text": reason})
        self.qty, self.pos = 0.0, None

    def check_stops(self, i: int, bar: list) -> None:
        hit = stop_reason(self.spec, self.pos, bar[1], bar[2], bar[3])
        if hit:
            self.sell(i, bar[0], hit[1], hit[0])
        else:
            self.pos.high_water = max(self.pos.high_water, bar[2])


def _simulate(spec: StrategySpec, bars: list, params: dict | None, start_cash: float) -> tuple[_Sim, list, int]:
    entry, exit_ = signal_series(spec, bars, params)
    sim = _Sim(spec, start_cash)
    equity, held, pending = [], 0, None
    last = len(bars) - 1
    for i, bar in enumerate(bars):
        t, o, _, _, c = bar[0], bar[1], bar[2], bar[3], bar[4]
        if pending == "buy" and sim.pos is None:
            if sim.buy(i, t, o):
                sim.check_stops(i, bar)
        elif pending == "sell" and sim.pos is not None:
            sim.sell(i, t, o, "signal")
        elif sim.pos is not None:
            sim.check_stops(i, bar)
        pending = None
        if sim.pos is not None:
            held += 1
        if i == last and sim.pos is not None:
            sim.sell(i, t, c, "end")
        equity.append(sim.cash + sim.qty * c)
        if i < last:
            pending = _next_order(sim, entry[i], exit_[i])
    return sim, equity, held


def _next_order(sim: _Sim, entry: bool, exit_: bool) -> str | None:
    if sim.pos is None:
        return "buy" if entry else None
    return "sell" if exit_ else None


def _prepare(spec: StrategySpec, bars: list, params: dict | None) -> StrategySpec:
    if len(bars) < MIN_BARS:
        raise ValueError(f"need at least {MIN_BARS} bars, got {len(bars)}")
    return with_params(spec, params)


def quick_metrics(spec: StrategySpec, bars: list, params: dict | None = None,
                  start_cash: float = BACKTEST_CASH) -> dict:
    spec = _prepare(spec, bars, None)
    sim, equity, held = _simulate(spec, bars, params, start_cash)
    return compute_metrics([b[0] for b in bars], equity, [b[4] for b in bars], sim.trades,
                           INTERVAL_SECONDS[spec.interval], start_cash, held)


def run_backtest(spec: StrategySpec, bars: list, *, start_cash: float = BACKTEST_CASH, params: dict | None = None,
                 symbol: str | None = None, interval: str | None = None, quote: str = "USD",
                 source_kind: str = "market") -> dict:
    spec = _prepare(spec, bars, params)
    sim, equity, held = _simulate(spec, bars, None, start_cash)
    closes = [b[4] for b in bars]
    interval = interval or spec.interval
    if interval not in INTERVAL_SECONDS:
        raise ValueError(f"unknown interval '{interval}'")
    metrics = compute_metrics([b[0] for b in bars], equity, closes, sim.trades,
                              INTERVAL_SECONDS[interval], start_cash, held)
    base = closes[0] or 1.0
    curve = [[b[0], e, start_cash * b[4] / base] for b, e in zip(bars, equity)]
    result = {
        "metrics": metrics,
        "curve": downsample(curve, CURVE_MAX),
        "trades": sim.trades,
        "markers": sim.markers,
        "data": {
            "symbol": symbol or spec.symbol, "interval": interval, "start": bars[0][0], "end": bars[-1][0],
            "bars": len(bars), "data_hash": data_hash(bars), "source_kind": source_kind, "quote": quote,
        },
        "quote": quote,
        "start_cash": start_cash,
        "spec_hash": spec_hash(spec),
        "engine_version": ENGINE_VERSION,
    }
    result = round_floats(result)
    result["result_hash"] = result_hash(result)
    return result
