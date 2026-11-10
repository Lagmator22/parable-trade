import logging
import re
from threading import Event
from typing import Callable, Literal

import anthropic
import httpx
from pydantic import BaseModel, Field

from parable import prices, referee
from parable.config import get_settings
from parable.jev import jev_decide
from parable.minds import (GOOGLE_BASE, LLM_TIMEOUT_S, claude_usable, extract_json, model_list,
                           note_claude_error)
from parable.models import PRESETS, BotRules, TradeDecision

log = logging.getLogger("parable.bot")

FALLBACK_TAG = "[fallback:rule]"
HISTORY_WINDOW = 12
DIP_BPS = 10
BAND_BPS = 20
DECISION_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["buy", "sell", "hold"]},
        "amount_dollars": {"type": "number", "description": "plain US dollars to trade, e.g. 20.5 means $20.50"},
        "reason": {"type": "string"},
    },
    "required": ["action", "amount_dollars", "reason"],
    "additionalProperties": False,
}
JSON_EXAMPLE = '{"action": "buy", "amount_dollars": 12.5, "reason": "short explanation"}'
DECISION_TOOL = {"name": "decide_trade", "description": "Decide the next paper trade.",
                 "input_schema": DECISION_SCHEMA, "strict": True}


class AiAnswer(BaseModel):
    action: Literal["buy", "sell", "hold"]
    amount_dollars: float = Field(default=0, ge=0, allow_inf_nan=False)
    reason: str


def redact(err: Exception) -> str:
    return f"{type(err).__name__}: " + re.sub(r"https?://\S+", "<url>", str(err))[:300]


def eth_value_usd(state: dict) -> int:
    return state["eth_wei"] * state["price"] // 10**20


def clamp(decision: TradeDecision, state: dict) -> TradeDecision:
    if decision.action == "hold":
        return decision
    have = state["cash_usd"] if decision.action == "buy" else eth_value_usd(state)
    amount = min(decision.amount_usd, state["max_trade_usd"], have)
    if amount <= 0:
        return TradeDecision(action="hold", reason=f"{decision.reason} (nothing to trade after limits)")
    return TradeDecision(action=decision.action, amount_usd=amount, reason=decision.reason)


def momentum_rule(state: dict) -> TradeDecision:
    prices_seen, size = state["history"], state["max_trade_usd"]
    if len(prices_seen) < 2:
        return TradeDecision(action="hold", reason="not enough price history yet")
    last, previous = prices_seen[-1], prices_seen[-2]
    if last > previous:
        return TradeDecision(action="buy", amount_usd=size, reason="price rising")
    if last < previous:
        return TradeDecision(action="sell", amount_usd=size, reason="price falling")
    return TradeDecision(action="hold", reason="no signal")


def dip_buyer_rule(state: dict) -> TradeDecision:
    prices_seen, size = state["history"], state["max_trade_usd"]
    if len(prices_seen) < 2:
        return TradeDecision(action="hold", reason="not enough price history yet")
    high, last = max(prices_seen), prices_seen[-1]
    if last * 10_000 < high * (10_000 - DIP_BPS):
        return TradeDecision(action="buy", amount_usd=size, reason="price is below its recent high")
    if last >= high and eth_value_usd(state) > 0:
        return TradeDecision(action="sell", amount_usd=size, reason="price recovered to its high")
    return TradeDecision(action="hold", reason="no signal")


def mean_revert_rule(state: dict) -> TradeDecision:
    prices_seen, size = state["history"], state["max_trade_usd"]
    if len(prices_seen) < 2:
        return TradeDecision(action="hold", reason="not enough price history yet")
    average, last = sum(prices_seen) // len(prices_seen), prices_seen[-1]
    if last * 10_000 > average * (10_000 + BAND_BPS):
        return TradeDecision(action="sell", amount_usd=size, reason="price is above its recent average")
    if last * 10_000 < average * (10_000 - BAND_BPS):
        return TradeDecision(action="buy", amount_usd=size, reason="price is below its recent average")
    return TradeDecision(action="hold", reason="price is near its average")


def yolo_rule(state: dict) -> TradeDecision:
    size = state["max_trade_usd"]
    buy = state["cash_usd"] >= size or eth_value_usd(state) < size
    return TradeDecision(action="buy" if buy else "sell", amount_usd=size, reason="yolo: max size")


RULES: dict[str, Callable[[dict], TradeDecision]] = {
    "momentum": momentum_rule,
    "dip_buyer": dip_buyer_rule,
    "mean_revert": mean_revert_rule,
    "yolo": yolo_rule,
}


def rule_decide(state: dict) -> TradeDecision:
    return RULES.get(state["strategy"], momentum_rule)(state)


def build_prompt(state: dict) -> str:
    history = [round(p / 1e8, 2) for p in state["history"]]

    def dollars(amount: int) -> float:
        return round(amount / 1e6, 2)

    return (
        f"You manage a small practice ETH/USD portfolio. Strategy: {state['strategy']}. "
        f"{PRESETS.get(state['strategy'], '')}\n"
        f"ETH price history in USD, oldest first: {history}\n"
        f"Cash: ${dollars(state['cash_usd'])}. ETH held: {state['eth_wei'] / 1e18:.6f} ETH. "
        f"Total equity: ${dollars(state['equity_usd'])}. Max per trade: ${dollars(state['max_trade_usd'])}. "
        f"Max loss allowed before you are shut down: {state['max_loss_bps'] / 100}%.\n"
        "Call decide_trade. amount_dollars is a plain number of US dollars, for example 20.5 means $20.50."
    )


def to_decision(raw: dict) -> TradeDecision:
    answer = AiAnswer.model_validate(raw)
    return TradeDecision(action=answer.action, amount_usd=round(answer.amount_dollars * 1_000_000),
                         reason=answer.reason)


def claude_decide(state: dict, model: str | None = None) -> TradeDecision:
    settings = get_settings()
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key, timeout=LLM_TIMEOUT_S)
    try:
        reply = client.messages.create(
            model=model or settings.bot_model, max_tokens=2000, tools=[DECISION_TOOL],
            tool_choice={"type": "auto"}, output_config={"effort": "low"},
            messages=[{"role": "user", "content": build_prompt(state)}],
        )
    except Exception as err:
        note_claude_error(err)
        raise
    block = next(b for b in reply.content if b.type == "tool_use")
    return to_decision(block.input)


def openai_style_decide(state: dict, base_url: str, api_key: str, model: str) -> TradeDecision:
    instruction = f"Reply with ONLY one JSON object, like {JSON_EXAMPLE} where action is one of buy, sell, hold."
    prompt = build_prompt(state).replace("Call decide_trade.", instruction)
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    response = httpx.post(f"{base_url.rstrip('/')}/chat/completions", timeout=LLM_TIMEOUT_S, headers=headers,
                          json={"model": model, "messages": [{"role": "user", "content": prompt}]})
    response.raise_for_status()
    return to_decision(extract_json(response.json()["choices"][0]["message"]["content"], "action"))


def build_brains() -> dict[str, dict]:
    settings = get_settings()
    brains = {"rule": {"decide": rule_decide, "ready": True}}
    for model in model_list(settings.claude_models):
        brains[f"claude:{model}"] = {"decide": lambda st, model=model: claude_decide(st, model),
                                     "ready": bool(settings.anthropic_api_key) and claude_usable()}
    for model in model_list(settings.jev_models):
        brains[f"jev:{model}"] = {"decide": lambda st, model=model: jev_decide(st, model),
                                  "ready": bool(settings.autoloops_api_key)}
    for family, models in (("gemini", settings.gemini_models), ("gemma", settings.gemma_models)):
        for model in model_list(models):
            brains[f"{family}:{model}"] = {
                "decide": lambda st, model=model: openai_style_decide(st, GOOGLE_BASE, settings.gemini_api_key,
                                                                      model),
                "ready": bool(settings.gemini_api_key),
            }
    return brains


def available_brains() -> dict[str, bool]:
    return {name: brain["ready"] for name, brain in build_brains().items()}


def decide(state: dict, brain: str = "rule") -> TradeDecision:
    entry = build_brains().get(brain)
    try:
        if entry is None or not entry["ready"]:
            raise RuntimeError(f"brain {brain} is not configured")
        decision = entry["decide"](state)
    except Exception:
        fallback = rule_decide(state)
        decision = fallback.model_copy(update={"reason": f"{FALLBACK_TAG} {fallback.reason}"})
    return clamp(decision, state)


def observe(samples: list[int], price: int) -> list[int]:
    if not samples:
        samples.extend(p for _, p in prices.history(HISTORY_WINDOW - 1))
    samples.append(price)
    del samples[:-HISTORY_WINDOW]
    return list(samples)


def read_state(run: dict, samples: list[int]) -> dict:
    price = prices.price()
    rules = run["rules"]
    return {
        "strategy": rules["strategy"], "history": observe(samples, price), "price": price,
        "cash_usd": run["cash_usd"], "eth_wei": run["eth_wei"], "equity_usd": referee.equity_at(run, price),
        "max_trade_usd": rules["max_trade_usd"], "max_loss_bps": rules["max_loss_bps"],
    }


def take_turn(run_id: int, rules: BotRules, samples: list[int]) -> None:
    run = referee.get_run(run_id)
    decision = decide(read_state(run, samples), rules.brain)
    if decision.action == "hold":
        return
    try:
        referee.trade(run_id, decision.action, decision.amount_usd, decision.reason)
    except referee.RefereeError:
        pass


def run_bot(run_id: int, rules: BotRules, stop_event: Event, interval_s: float = 15) -> None:
    samples: list[int] = []
    while not stop_event.is_set():
        try:
            if referee.get_run(run_id)["status"] != "alive":
                return
            take_turn(run_id, rules, samples)
            if referee.check(run_id) is not None:
                return
        except referee.RunNotFound:
            return
        except Exception as err:
            log.warning("bot turn for run %s skipped: %s", run_id, redact(err))
        stop_event.wait(interval_s)
