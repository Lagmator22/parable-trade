import json
import re
import time

import anthropic
import httpx

from parable.config import get_settings

NO_CREDIT_PAUSE_S = 600
LLM_TIMEOUT_S = 30
GOOGLE_BASE = "https://generativelanguage.googleapis.com/v1beta/openai"
CHAT_MAX_TOKENS = 1500

_claude_off_until = 0.0


def note_claude_error(err: Exception) -> None:
    global _claude_off_until
    if "credit balance" in str(err).lower():
        _claude_off_until = time.time() + NO_CREDIT_PAUSE_S


def claude_usable() -> bool:
    return time.time() >= _claude_off_until


def model_list(raw: str) -> list[str]:
    return [model.strip() for model in raw.split(",") if model.strip()]


def probe_claude() -> None:
    settings = get_settings()
    models = model_list(settings.claude_models)
    if not settings.anthropic_api_key or not models:
        return
    try:
        anthropic.Anthropic(api_key=settings.anthropic_api_key, timeout=20).messages.create(
            model=models[0], max_tokens=1, messages=[{"role": "user", "content": "ok"}])
    except Exception as err:
        note_claude_error(err)


def extract_json(text: str, required_key: str | None = None) -> dict:
    text = re.sub(r"<(thought|thinking)>.*?</\1>", "", text, flags=re.DOTALL)
    text = text.replace("```json", "").replace("```", "")
    found, decoder, index = None, json.JSONDecoder(), 0
    while True:
        index = text.find("{", index)
        if index < 0:
            break
        try:
            candidate, end = decoder.raw_decode(text[index:])
        except ValueError:
            index += 1
            continue
        index += end
        if isinstance(candidate, dict) and (required_key is None or required_key in candidate):
            found = candidate
    if found is None:
        raise ValueError("no JSON answer in the model reply")
    return found


def claude_json(model: str, prompt: str) -> dict:
    client = anthropic.Anthropic(api_key=get_settings().anthropic_api_key, timeout=LLM_TIMEOUT_S)
    try:
        reply = client.messages.create(model=model, max_tokens=CHAT_MAX_TOKENS, output_config={"effort": "low"},
                                       messages=[{"role": "user", "content": prompt}])
    except Exception as err:
        note_claude_error(err)
        raise
    return extract_json("".join(block.text for block in reply.content if block.type == "text"))


def google_json(model: str, prompt: str) -> dict:
    response = httpx.post(f"{GOOGLE_BASE}/chat/completions", timeout=LLM_TIMEOUT_S,
                          headers={"Authorization": f"Bearer {get_settings().gemini_api_key}"},
                          json={"model": model, "messages": [{"role": "user", "content": prompt}]})
    response.raise_for_status()
    return extract_json(response.json()["choices"][0]["message"]["content"])


def chat_json(brain: str, prompt: str) -> dict:
    family, _, model = brain.partition(":")
    if family == "claude":
        return claude_json(model, prompt)
    if family in ("gemini", "gemma"):
        return google_json(model, prompt)
    raise ValueError(f"{brain} is not an AI brain")
