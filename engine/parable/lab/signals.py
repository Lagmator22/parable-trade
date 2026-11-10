from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

from ..models import StrategySpec
from .consts import INTERVAL_SECONDS
from .formula import evaluate, parse
from .spec import resolve_params, warmup_bars

Bar = list[float]


@dataclass
class Position:
    entry_price: float
    entry_t: float
    high_water: float


@dataclass
class Decision:
    action: Literal["buy", "sell", "hold"]
    reason: str


@lru_cache(maxsize=512)
def _parsed(text: str):
    return parse(text)


def bar_columns(bars: list[Bar]) -> dict[str, list[float]]:
    names = ("open", "high", "low", "close", "volume")
    return {name: [bar[i + 1] for bar in bars] for i, name in enumerate(names)}


def _flags(values: list, warm: int) -> list[bool]:
    return [i >= warm and v is True for i, v in enumerate(values)]


def signal_series(spec: StrategySpec, bars: list[Bar], params: dict | None = None) -> tuple[list[bool], list[bool]]:
    values = resolve_params(spec, params)
    columns = bar_columns(bars)
    warm = warmup_bars(spec, params)
    entry = _flags(evaluate(_parsed(spec.entry.strip()), columns, values), warm)
    if not spec.exit.strip():
        return entry, [False] * len(bars)
    return entry, _flags(evaluate(_parsed(spec.exit.strip()), columns, values), warm)


def decide(spec: StrategySpec, bars: list[Bar], position: Position | None) -> Decision:
    if not bars:
        return Decision("hold", "no bars")
    entry, exit_ = signal_series(spec, bars)
    if position is None:
        return Decision("buy", "entry") if entry[-1] else Decision("hold", "flat")
    return Decision("sell", "signal") if exit_[-1] else Decision("hold", "holding")


def stop_reason(spec: StrategySpec, position: Position, bar_open: float, bar_high: float,
                bar_low: float) -> tuple[str, float] | None:
    entry = position.entry_price
    downs = []
    if spec.stop_loss_pct > 0:
        downs.append((entry * (1 - spec.stop_loss_pct / 100), 0, "stop"))
    if spec.trailing_stop_pct > 0:
        downs.append((position.high_water * (1 - spec.trailing_stop_pct / 100), 1, "trailing"))
    hit = [(level, -rank, name) for level, rank, name in downs if bar_low <= level]
    if hit:
        level, _, name = max(hit)
        return name, min(level, bar_open)
    if spec.take_profit_pct > 0:
        target = entry * (1 + spec.take_profit_pct / 100)
        if bar_high >= target:
            return "take_profit", max(target, bar_open)
    return None


def closed_bars(bars: list[Bar], interval: str, now: float) -> list[Bar]:
    seconds = INTERVAL_SECONDS[interval]
    return [bar for bar in bars if bar[0] + seconds <= now]
