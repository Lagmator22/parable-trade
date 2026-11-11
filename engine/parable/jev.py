import httpx

from parable.config import get_settings
from parable.errors import LabError

JEV_URL = "https://api.autoloops.ai/v1/systemone"
TIMEOUT_S = 20


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
