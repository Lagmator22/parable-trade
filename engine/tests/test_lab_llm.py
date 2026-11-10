import json
import logging

import httpx
import pytest

from parable.config import get_settings
from parable.errors import LabError
from parable.lab import llm
from parable.lab.llm import AiAuth

KEY = "sk-test-SECRET-key-0123456789"


@pytest.fixture(autouse=True)
def reset_transport():
    yield
    llm.set_transport(None)


def use(handler):
    llm.set_transport(httpx.MockTransport(handler))


def set_env(monkeypatch, **values):
    for name, value in values.items():
        monkeypatch.setenv(name.upper(), value)
    get_settings.cache_clear()


def test_auth_from_headers():
    assert llm.auth_from_headers(None, None, None) is None
    assert llm.auth_from_headers("", " ", "") is None
    auth = llm.auth_from_headers("OpenAI", "gpt-5-mini", f" {KEY} ")
    assert auth.provider == "openai" and auth.model == "gpt-5-mini" and auth.key == KEY
    for args in (("openai", None, KEY), ("openai", "m", None), (None, "m", KEY), ("mistral", "m", KEY),
                 ("openai", "bad model!", KEY), ("openai", "x" * 90, KEY)):
        with pytest.raises(LabError) as err:
            llm.auth_from_headers(*args)
        assert err.value.status == 400 and err.value.code == "bad_request" and KEY not in err.value.detail


def test_key_hidden_from_repr_and_dump():
    auth = AiAuth(provider="openai", model="m", key=KEY)
    assert KEY not in repr(auth) and KEY not in str(auth)
    assert KEY not in json.dumps(auth.model_dump()) and KEY not in auth.model_dump_json()


def test_redact():
    assert llm.redact(f"bad {KEY} and {KEY}", KEY) == "bad *** and ***"
    assert llm.redact("plain", None) == "plain"


def test_openai_request_shape_and_parse():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": 'noise {"a": 1} tail'}}]})

    use(handler)
    auth = AiAuth(provider="openai", model="gpt-5-mini", key=KEY)
    assert llm.chat_json(auth, "hi", system="be brief") == {"a": 1}
    assert seen["url"] == "https://api.openai.com/v1/chat/completions" and seen["auth"] == f"Bearer {KEY}"
    assert seen["body"]["response_format"] == {"type": "json_object"}
    assert seen["body"]["messages"][0] == {"role": "system", "content": "be brief"}
    assert KEY not in seen["url"]


def test_anthropic_request_shape_and_parse():
    seen = {}

    def handler(request):
        seen["headers"] = dict(request.headers)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"content": [{"type": "text", "text": '```json\n{"ok": true}\n```'}]})

    use(handler)
    assert llm.chat_json(AiAuth(provider="anthropic", model="claude-x", key=KEY), "hi", system="sys") == {"ok": True}
    assert seen["headers"]["x-api-key"] == KEY and seen["headers"]["anthropic-version"]
    assert seen["body"]["system"] == "sys" and seen["body"]["messages"][0]["content"] == "hi"


def test_gemini_own_key_request_shape_and_parse():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["key"] = request.headers["x-goog-api-key"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": '{"v": 2}'}]}}]})

    use(handler)
    assert llm.chat_json(AiAuth(provider="gemini", model="gemini-x", key=KEY), "hi", system="sys") == {"v": 2}
    assert seen["url"].endswith("/models/gemini-x:generateContent") and KEY not in seen["url"] and seen["key"] == KEY
    assert seen["body"]["generationConfig"]["responseMimeType"] == "application/json"
    assert seen["body"]["systemInstruction"]["parts"][0]["text"] == "sys"


def test_platform_models_use_server_key(monkeypatch):
    set_env(monkeypatch, gemini_api_key="platform-key-xyz")
    seen = {}

    def handler(request):
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"x": 1}'}}]})

    use(handler)
    assert llm.chat_json(AiAuth(provider="platform", model="gemma:gemma-4"), "hi", system="sys") == {"x": 1}
    assert seen["auth"] == "Bearer platform-key-xyz" and seen["body"]["model"] == "gemma-4"
    assert seen["body"]["messages"][0]["content"].startswith("sys")
    with pytest.raises(LabError) as err:
        llm.chat_json(AiAuth(provider="platform", model="jev:thing"), "hi")
    assert err.value.code == "model_unavailable"
    set_env(monkeypatch, gemini_api_key="")
    with pytest.raises(LabError) as err:
        llm.chat_json(AiAuth(provider="platform", model="gemini:x"), "hi")
    assert err.value.status == 503 and err.value.code == "model_unavailable"


def test_error_mapping():
    auth = AiAuth(provider="openai", model="m", key=KEY)
    cases = [(401, "bad_key", 401), (403, "bad_key", 401), (429, "rate_limited", 429),
             (500, "model_unavailable", 503), (404, "model_unavailable", 503)]
    for status, code, http in cases:
        use(lambda r, s=status: httpx.Response(s, headers={"retry-after": "7"}, text="nope"))
        with pytest.raises(LabError) as err:
            llm.chat_json(auth, "hi")
        assert err.value.code == code and err.value.status == http
        if status == 429:
            assert err.value.extra == {"retry_after": 7}
    use(lambda r: httpx.Response(200, json={"choices": [{"message": {"content": "no json here"}}]}))
    with pytest.raises(LabError) as err:
        llm.chat_json(auth, "hi")
    assert err.value.code == "bad_output" and err.value.status == 502
    use(lambda r: httpx.Response(200, text="<html>"))
    with pytest.raises(LabError) as err:
        llm.chat_json(auth, "hi")
    assert err.value.code == "bad_output"
    use(lambda r: httpx.Response(200, json={"choices": []}))
    with pytest.raises(LabError) as err:
        llm.chat_json(auth, "hi")
    assert err.value.code == "bad_output"


def test_key_never_leaks_through_errors_or_logs(caplog):
    caplog.set_level(logging.DEBUG)
    auth = AiAuth(provider="openai", model="m", key=KEY)

    def echo(request):
        return httpx.Response(400, text=f"invalid key provided: {KEY}")

    def down(request):
        raise httpx.ConnectError(f"cannot connect with {KEY}")

    for handler in (echo, down, lambda r: httpx.Response(500, text=KEY), lambda r: httpx.Response(401, text=KEY),
                    lambda r: httpx.Response(429, text=KEY)):
        use(handler)
        with pytest.raises(LabError) as err:
            llm.chat_json(auth, "prompt")
        blob = f"{err.value} {err.value.detail} {err.value.extra} {err.value.__cause__} {err.value.__context__}"
        assert KEY not in blob and KEY not in repr(err.value)
    assert KEY not in caplog.text
    use(echo)
    with pytest.raises(LabError) as err:
        llm.chat_json(auth, "prompt")
    assert "***" in err.value.detail


def test_missing_key_for_own_provider():
    with pytest.raises(LabError) as err:
        llm.chat_json(AiAuth(provider="openai", model="m"), "hi")
    assert err.value.code == "bad_key"


def test_platform_models_listing(monkeypatch):
    set_env(monkeypatch, gemini_api_key="", autoloops_api_key="", gemini_models="", gemma_models="", jev_models="a,b")
    listed = llm.platform_models()
    assert [m.id for m in listed] == ["jev:a", "jev:b"] and not any(m.available for m in listed)
    set_env(monkeypatch, gemini_api_key="g", autoloops_api_key="j", gemini_models="m1, m2", gemma_models="gm")
    listed = {m.id: m for m in llm.platform_models()}
    assert set(listed) == {"gemini:m1", "gemini:m2", "gemma:gm", "jev:a", "jev:b"}
    assert all(m.available and m.free for m in listed.values())
    assert listed["gemma:gm"].provider == "gemma" and listed["gemma:gm"].model == "gm"
    set_env(monkeypatch, gemini_models="", gemma_models="")
    assert "gemini:gemini-3.5-flash-lite" in {m.id for m in llm.platform_models()}


def test_own_models_filtered_and_defaults():
    use(lambda r: httpx.Response(200, json={"data": [{"id": "gpt-5"}, {"id": "text-embedding-3"}, {"id": "whisper-1"},
                                                      {"id": "o3-mini"}, {"id": "dall-e-3"}]}))
    models = llm.own_models(AiAuth(provider="openai", model="x", key=KEY))
    assert [m.id for m in models] == ["openai:gpt-5", "openai:o3-mini"] and not any(m.free for m in models)
    use(lambda r: httpx.Response(200, json={"models": [
        {"name": "models/gemini-a", "supportedGenerationMethods": ["generateContent"]},
        {"name": "models/embedding-001", "supportedGenerationMethods": ["embedContent"]}]}))
    assert [m.model for m in llm.own_models(AiAuth(provider="gemini", model="x", key=KEY))] == ["gemini-a"]
    use(lambda r: httpx.Response(200, json={"data": [{"id": "claude-a"}]}))
    assert [m.model for m in llm.own_models(AiAuth(provider="anthropic", model="x", key=KEY))] == ["claude-a"]
    use(lambda r: httpx.Response(401, text=KEY))
    fallback = llm.own_models(AiAuth(provider="anthropic", model="x", key=KEY))
    assert fallback and all(m.available for m in fallback)
    use(lambda r: httpx.Response(200, json={"weird": 1}))
    assert llm.own_models(AiAuth(provider="openai", model="x", key=KEY))


QUESTIONS = {"family": {"instructions": "pick", "options": ["trend", "dip"]},
             "size": {"instructions": "size", "options": ["small", "full"]}}


def test_jev_choices(monkeypatch):
    set_env(monkeypatch, autoloops_api_key="jev-secret-key")
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"answers": {"family": {"choice": "dip"}, "size": {"choice": "full"}}})

    use(handler)
    assert llm.jev_choices("gemma-4", "buy the dip, all in", QUESTIONS) == {"family": "dip", "size": "full"}
    assert seen["url"] == "https://api.autoloops.ai/v1/systemone" and seen["auth"] == "Bearer jev-secret-key"
    body = seen["body"]
    assert body["model"] == "gemma-4" and body["state"][0]["content"][0]["text"] == "buy the dip, all in"
    assert body["questions"]["family"] == {"type": "choice", "instructions": "pick", "criteria": {"trend": None, "dip": None}}


def test_jev_choices_errors(monkeypatch, caplog):
    set_env(monkeypatch, autoloops_api_key="")
    with pytest.raises(LabError) as err:
        llm.jev_choices("m", "s", QUESTIONS)
    assert err.value.code == "model_unavailable"
    set_env(monkeypatch, autoloops_api_key="jev-secret-key")
    use(lambda r: httpx.Response(200, json={"answers": {"family": {"choice": "moon"}, "size": {"choice": "full"}}}))
    with pytest.raises(LabError) as err:
        llm.jev_choices("m", "s", QUESTIONS)
    assert err.value.code == "bad_output"
    use(lambda r: httpx.Response(200, json={"nothing": 1}))
    with pytest.raises(LabError):
        llm.jev_choices("m", "s", QUESTIONS)
    use(lambda r: httpx.Response(429, text="slow down"))
    with pytest.raises(LabError) as err:
        llm.jev_choices("m", "s", QUESTIONS)
    assert err.value.code == "rate_limited"
    use(lambda r: httpx.Response(500, text="jev-secret-key"))
    with pytest.raises(LabError) as err:
        llm.jev_choices("m", "s", QUESTIONS)
    assert "jev-secret-key" not in err.value.detail and "jev-secret-key" not in caplog.text
