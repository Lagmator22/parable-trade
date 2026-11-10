import logging
import threading

from parable import minds
from parable.config import get_settings

log = logging.getLogger("parable.analyst")

AI_TIMEOUT_S = 6.0
GOOGLE_FAMILIES = ("gemini", "gemma")


def brain_name() -> str:
    return get_settings().ai_analyst_brain


def available() -> bool:
    settings = get_settings()
    family = brain_name().partition(":")[0]
    if family == "claude":
        return bool(settings.anthropic_api_key) and minds.claude_usable()
    if family in GOOGLE_FAMILIES:
        return bool(settings.gemini_api_key)
    return False


def ask(prompt: str, timeout: float = AI_TIMEOUT_S) -> dict | None:
    if not available():
        return None
    outcome: dict = {}

    def work() -> None:
        try:
            outcome["answer"] = minds.chat_json(brain_name(), prompt)
        except Exception as err:
            outcome["failure"] = type(err).__name__

    worker = threading.Thread(target=work, daemon=True, name="analyst-call")
    worker.start()
    worker.join(timeout)
    if "failure" in outcome:
        log.warning("analyst call failed: %s", outcome["failure"])
    answer = outcome.get("answer")
    return answer if isinstance(answer, dict) else None
