import httpx

from parable.config import get_settings
from parable.errors import LabError
from parable.models import TradeDecision

JEV_URL = "https://api.autoloops.ai/v1/systemone"
CHOICES = ("buy", "sell", "hold")
TIMEOUT_S = 20
MIN_TRADE_USD = 1_000_000


def questions_body(model: str, situation: str, questions: dict) -> dict:
    return {
        "model": model,
        "state": [{"role": "user", "content": [{"type": "text", "text": situation}]}],
        "questions": {qid: {"type": "choice", "instructions": q["instructions"],
                            "criteria": {option: None for option in q["options"]}}
                      for qid, q in questions.items()},
    }


def post_body(body: dict, transport: httpx.BaseTransport | None = None) -> dict:
    key = get_settings().autoloops_api_key
    if not key:
        raise LabError(503, "model_unavailable", "Jev is not configured")
    response = None
    try:
        with httpx.Client(timeout=TIMEOUT_S, transport=transport) as client:
            response = client.post(JEV_URL, json=body, headers={"Authorization": f"Bearer {key}"})
    except httpx.HTTPError:
        pass
    if response is None:
        raise LabError(503, "model_unavailable", "Jev is unreachable")
    if response.status_code == 429:
        raise LabError(429, "rate_limited", "Jev is busy, try again shortly", {"retry_after": 30})
    if response.status_code >= 400:
        raise LabError(503, "model_unavailable", f"Jev answered HTTP {response.status_code}")
    try:
        answers = response.json()["answers"]
    except (ValueError, KeyError, TypeError):
        answers = None
    if not isinstance(answers, dict):
        raise LabError(502, "bad_output", "Jev sent an unreadable answer")
    return answers


def ask(model: str, situation: str, questions: dict, transport: httpx.BaseTransport | None = None) -> dict:
    return post_body(questions_body(model, situation, questions), transport)


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
