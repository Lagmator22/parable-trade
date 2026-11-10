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
