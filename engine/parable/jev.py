import httpx

from parable.config import get_settings
from parable.models import TradeDecision

JEV_URL = "https://api.autoloops.ai/v1/systemone"
CHOICES = ("buy", "sell", "hold")
TIMEOUT_S = 20
MIN_TRADE_USD = 1_000_000


def jev_question(state: dict) -> dict:
    from parable.bot_runner import build_prompt

    situation = build_prompt(state).split("Call decide_trade.")[0].strip()
    return {
        "state": [{"role": "user", "content": [{"type": "text", "text": situation}]}],
        "questions": {"action": {
            "type": "choice",
            "instructions": "Following the strategy above, what should the bot do right now?",
            "criteria": {choice: None for choice in CHOICES},
        }},
    }


def to_decision(answer: dict, max_trade_usd: int) -> TradeDecision:
    probabilities = {c: float(answer.get("probabilities", {}).get(c, 0.0)) for c in CHOICES}
    choice = str(answer.get("choice") or max(probabilities, key=probabilities.get))
    if choice not in CHOICES:
        raise ValueError(f"unexpected Jev choice {choice!r}")
    confidence = probabilities.get(choice, 0.0)
    amount = 0 if choice == "hold" else max(MIN_TRADE_USD, int(max_trade_usd * confidence))
    odds = " · ".join(f"{c} {probabilities[c]:.0%}" for c in CHOICES)
    return TradeDecision(action=choice, amount_usd=amount, reason=f"Jev: {choice} ({odds})")


def jev_decide(state: dict, model: str) -> TradeDecision:
    response = httpx.post(JEV_URL, timeout=TIMEOUT_S, json={"model": model, **jev_question(state)},
                          headers={"Authorization": f"Bearer {get_settings().autoloops_api_key}"})
    response.raise_for_status()
    return to_decision(response.json()["answers"]["action"], state["max_trade_usd"])
