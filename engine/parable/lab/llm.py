import json
import logging
import re
import time
from typing import Literal

import httpx
from pydantic import BaseModel, Field

from parable import jev, minds
from parable.config import get_settings
from parable.errors import LabError

log = logging.getLogger("parable.lab.llm")

PROVIDERS = ("openai", "anthropic", "gemini")
MODEL_NAME = re.compile(r"^[A-Za-z0-9._:/\-]{1,80}$")
GOOGLE_COMPAT = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
GOOGLE_NATIVE = "https://generativelanguage.googleapis.com/v1beta"
OPENAI_BASE = "https://api.openai.com/v1"
ANTHROPIC_BASE = "https://api.anthropic.com/v1"
MAX_TOKENS = 3000
DEFAULT_GEMINI = "gemini-3.5-flash-lite"
DEFAULTS = {
    "openai": ["gpt-5-mini", "gpt-5"],
    "anthropic": ["claude-haiku-5-5", "claude-sonnet-5-5"],
    "gemini": ["gemini-3.5-flash-lite", "gemini-3.5-flash"],
}
NOT_CHAT = ("embedding", "whisper", "tts", "dall", "image", "audio", "realtime", "moderation", "transcribe", "search")
BODY_CHARS = 200
RETRY_PAUSE = 2.0

_transport: httpx.BaseTransport | None = None


class AiAuth(BaseModel):
    provider: Literal["openai", "anthropic", "gemini", "platform"]
    model: str
    key: str | None = Field(default=None, repr=False, exclude=True)


class ModelInfo(BaseModel):
    id: str
    provider: str
    model: str
    label: str
    available: bool
    free: bool


def set_transport(transport: httpx.BaseTransport | None) -> None:
    global _transport
    _transport = transport


def redact(text: str, key: str | None) -> str:
    text = str(text)
    return text.replace(key, "***") if key else text


def auth_from_headers(provider: str | None, model: str | None, key: str | None) -> AiAuth | None:
    provider, model, key = (provider or "").strip().lower(), (model or "").strip(), (key or "").strip()
    if not (provider or model or key):
        return None
    if not (provider and model and key):
        raise LabError(400, "bad_request", "send x-ai-provider, x-ai-model and x-ai-key together")
    if provider not in PROVIDERS:
        raise LabError(400, "bad_request", "x-ai-provider must be openai, anthropic or gemini")
    if not MODEL_NAME.match(model):
        raise LabError(400, "bad_request", "x-ai-model is not a valid model name")
    return AiAuth(provider=provider, model=model, key=key)


def call(method: str, url: str, key: str | None, timeout: float, **kwargs) -> dict:
    response = None
    try:
        with httpx.Client(timeout=timeout, transport=_transport) as client:
            response = client.request(method, url, **kwargs)
    except httpx.HTTPError:
        pass
    if response is None:
        raise LabError(503, "model_unavailable", "the AI provider could not be reached")
    status = response.status_code
    if status >= 400:
        body = redact(response.text[:BODY_CHARS], key)
        log.info("ai provider answered %s", status)
        if status in (401, 403):
            raise LabError(401, "bad_key", "the AI provider rejected that key")
        if status == 429:
            wait = response.headers.get("retry-after", "30")
            raise LabError(429, "rate_limited", "the AI provider is rate limiting, try again shortly",
                           {"retry_after": int(wait) if wait.isdigit() else 30})
        raise LabError(503 if status != 400 else 502, "model_unavailable" if status != 400 else "bad_output",
                       f"the AI provider answered HTTP {status}: {body}")
    try:
        data = response.json()
    except ValueError:
        data = None
    if not isinstance(data, dict):
        raise LabError(502, "bad_output", "the AI provider sent an unreadable answer")
    return data


def whole_json(text: str) -> dict | None:
    cleaned = re.sub(r"<(thought|thinking)>.*?</\1>", "", text, flags=re.DOTALL)
    cleaned = cleaned.replace("```json", "").replace("```", "").strip()
    decoder = json.JSONDecoder()
    for index, char in enumerate(cleaned):
        if char == "{":
            try:
                candidate, _ = decoder.raw_decode(cleaned[index:])
            except ValueError:
                continue
            if isinstance(candidate, dict):
                return candidate
    return None


def parse_reply(text: str) -> dict:
    found = whole_json(text)
    if found is None:
        try:
            found = minds.extract_json(text)
        except ValueError:
            found = None
    if found is None:
        raise LabError(502, "bad_output", "the model did not return JSON")
    return found


def openai_style(url: str, key: str, model: str, prompt: str, system: str | None, timeout: float, json_mode: bool) -> str:
    messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
    body = {"model": model, "messages": messages}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    data = call("POST", url, key, timeout, json=body, headers={"Authorization": f"Bearer {key}"})
    try:
        return data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        raise LabError(502, "bad_output", "the model sent an empty answer") from None


def anthropic_text(key: str, model: str, prompt: str, system: str | None, timeout: float) -> str:
    body = {"model": model, "max_tokens": MAX_TOKENS, "messages": [{"role": "user", "content": prompt}]}
    if system:
        body["system"] = system
    data = call("POST", f"{ANTHROPIC_BASE}/messages", key, timeout, json=body,
                headers={"x-api-key": key, "anthropic-version": "2023-06-01"})
    return "".join(b.get("text", "") for b in data.get("content", []) if isinstance(b, dict))


def gemini_text(key: str, model: str, prompt: str, system: str | None, timeout: float) -> str:
    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json"}}
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    data = call("POST", f"{GOOGLE_NATIVE}/models/{model}:generateContent", key, timeout, json=body,
                headers={"x-goog-api-key": key})
    try:
        return "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"])
    except (KeyError, IndexError, TypeError):
        raise LabError(502, "bad_output", "the model sent an empty answer") from None


def platform_text(model_id: str, prompt: str, system: str | None, timeout: float) -> str:
    family, _, model = model_id.partition(":")
    key = get_settings().gemini_api_key
    if family not in ("gemini", "gemma") or not model or not key:
        raise LabError(503, "model_unavailable", "that model is not available right now")
    full = f"{system}\n\n{prompt}" if system else prompt
    return openai_style(GOOGLE_COMPAT, key, model, full, None, timeout, False)


def platform_reply(model: str, prompt: str, system: str | None, timeout: float) -> str:
    for attempt in (1, 2):
        try:
            return platform_text(model, prompt, system, timeout)
        except LabError as err:
            if err.code == "bad_key":
                raise LabError(503, "model_unavailable", "that model is not available right now") from None
            if err.code != "model_unavailable" or attempt == 2:
                raise
            time.sleep(RETRY_PAUSE)
    raise LabError(503, "model_unavailable", "that model is not available right now")


def chat_json(auth: AiAuth, prompt: str, *, system: str | None = None, timeout: float = 45) -> dict:
    key = auth.key
    if auth.provider == "platform":
        text = platform_reply(auth.model, prompt, system, timeout)
    elif not key:
        raise LabError(401, "bad_key", "no API key was provided")
    elif auth.provider == "openai":
        text = openai_style(f"{OPENAI_BASE}/chat/completions", key, auth.model, prompt, system, timeout, True)
    elif auth.provider == "anthropic":
        text = anthropic_text(key, auth.model, prompt, system, timeout)
    else:
        text = gemini_text(key, auth.model, prompt, system, timeout)
    return parse_reply(text)


def jev_choices(model: str, situation: str, questions: dict) -> dict[str, str]:
    answers = jev.ask(model, situation, questions, _transport)
    out: dict[str, str] = {}
    for qid, spec in questions.items():
        choice = (answers.get(qid) or {}).get("choice") if isinstance(answers.get(qid), dict) else None
        if choice not in spec["options"]:
            raise LabError(502, "bad_output", "Jev gave an answer outside the options")
        out[qid] = str(choice)
    return out


def split_names(raw: str) -> list[str]:
    return minds.model_list(raw)


def platform_models() -> list[ModelInfo]:
    settings = get_settings()
    gemini_key, jev_key = bool(settings.gemini_api_key), bool(settings.autoloops_api_key)
    gemini = split_names(settings.gemini_models) or ([DEFAULT_GEMINI] if gemini_key else [])
    out = [ModelInfo(id=f"gemini:{m}", provider="gemini", model=m, label=m, available=gemini_key, free=True) for m in gemini]
    out += [ModelInfo(id=f"gemma:{m}", provider="gemma", model=m, label=m, available=gemini_key, free=True)
            for m in split_names(settings.gemma_models)]
    out += [ModelInfo(id=f"jev:{m}", provider="jev", model=m, label=f"Jev {m}", available=jev_key, free=True)
            for m in split_names(settings.jev_models)]
    return out


def listed(auth: AiAuth) -> list[str]:
    key, timeout = auth.key or "", 8
    if auth.provider == "openai":
        data = call("GET", f"{OPENAI_BASE}/models", key, timeout, headers={"Authorization": f"Bearer {key}"})
        ids = [m["id"] for m in data.get("data", [])]
        return sorted(i for i in ids if re.match(r"^(gpt|o\d)", i) and not any(n in i for n in NOT_CHAT))
    if auth.provider == "anthropic":
        data = call("GET", f"{ANTHROPIC_BASE}/models", key, timeout,
                    headers={"x-api-key": key, "anthropic-version": "2023-06-01"})
        return [m["id"] for m in data.get("data", [])]
    data = call("GET", f"{GOOGLE_NATIVE}/models", key, timeout, headers={"x-goog-api-key": key})
    return [m["name"].removeprefix("models/") for m in data.get("models", [])
            if "generateContent" in m.get("supportedGenerationMethods", []) and m["name"].startswith("models/gemini")]


def own_models(auth: AiAuth) -> list[ModelInfo]:
    try:
        names = listed(auth)[:40]
    except (LabError, KeyError, TypeError, AttributeError):
        names = []
    names = names or DEFAULTS.get(auth.provider, [])
    return [ModelInfo(id=f"{auth.provider}:{m}", provider=auth.provider, model=m, label=m, available=True, free=False)
            for m in names]
