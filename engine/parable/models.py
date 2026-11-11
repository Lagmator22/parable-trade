import hashlib
from typing import Literal

from pydantic import BaseModel, Field

PRESETS = {
    "momentum": "Buy when the price is rising over the recent history, sell when it is falling.",
    "dip_buyer": "Buy when the price dipped below its recent high, sell some after it recovers.",
    "mean_revert": "Sell into sharp rises, buy into sharp drops, expecting the price to return to its recent average.",
    "yolo": "Always trade the maximum allowed size, buying if you hold cash, selling if you hold ETH.",
}


class BotRules(BaseModel):
    strategy: str
    brain: str = "rule"
    start_cash_usd: int = Field(default=1_000_000_000, gt=0)
    max_trade_usd: int = Field(default=250_000_000, gt=0)
    max_loss_bps: int = Field(default=300, gt=0)
    lease_seconds: int = Field(default=300, gt=0)


class TradeDecision(BaseModel):
    action: Literal["buy", "sell", "hold"]
    amount_usd: int = 0
    reason: str


def fingerprint(rules: BotRules) -> str:
    preset = PRESETS.get(rules.strategy, "")
    spec = f"{rules.brain}:{rules.strategy}:{preset}:{rules.max_trade_usd}:{rules.max_loss_bps}"
    return "0x" + hashlib.sha256(spec.encode()).hexdigest()[:16]


class RunRules(BaseModel):
    version_id: str
    spec_hash: str
    symbol: str
    interval: str
    quote: str = "USD"
    start_cash: int = Field(default=10_000_000_000, gt=0)
    max_trade: int = Field(default=10_000_000_000, gt=0)
    max_loss_bps: int = Field(default=2000, gt=0, le=10_000)
    lease_seconds: int = Field(default=86_400, gt=0, le=2_592_000)


class ParamSpec(BaseModel):
    value: float
    min: float
    max: float
    step: float = Field(default=1.0, gt=0)


class StrategySpec(BaseModel):
    name: str = Field(default="Untitled", max_length=60)
    summary: str = Field(default="", max_length=300)
    symbol: str = Field(max_length=64)
    interval: str = Field(max_length=4)
    built_by: str = Field(default="manual", max_length=80)
    params: dict[str, ParamSpec] = Field(default_factory=dict)
    entry: str = Field(min_length=1, max_length=400)
    exit: str = Field(default="", max_length=400)
    size_pct: float = Field(default=100.0, gt=0, le=100)
    stop_loss_pct: float = Field(default=0.0, ge=0, le=50)
    take_profit_pct: float = Field(default=0.0, ge=0, le=1000)
    trailing_stop_pct: float = Field(default=0.0, ge=0, le=50)
    fee_bps: float = Field(default=10.0, ge=0, le=200)
    slippage_bps: float = Field(default=5.0, ge=0, le=200)


class NewListing(BaseModel):
    version_id: str
    title: str = Field(min_length=3, max_length=80)
    pitch: str = Field(default="", max_length=600)
    price_cents: int = Field(ge=100, le=50_000)
    mode: Literal["hold", "instant"] = "hold"
    trial_s: int = Field(default=3600, ge=60, le=259_200)
    min_return_bps: int = Field(default=0, ge=0, le=5000)
    max_loss_bps: int = Field(default=2000, ge=10, le=5000)
    proof_id: str
    allow_test_drive: bool = True
