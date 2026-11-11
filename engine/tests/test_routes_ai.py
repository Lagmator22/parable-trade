import logging

from agents_support import INTERVAL, SYMBOL, clean_lab, fake_chat, llm_spec, make_client, spec_dict
from parable.config import get_settings
from parable.errors import LabError
from parable.lab import llm

KEY = "sk-very-secret-key"
OWN = {"x-ai-provider": "openai", "x-ai-model": "gpt-5-mini", "x-ai-key": KEY}


def platform(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "g-platform")
    monkeypatch.setenv("GEMINI_MODELS", "gemini-3.5-flash-lite")
    get_settings.cache_clear()
    return "gemini:gemini-3.5-flash-lite"


def test_ai_models_and_key_check(monkeypatch):
    name = platform(monkeypatch)
    client = make_client()
    base = client.get("/api/ai/models").json()
    assert base["key_ok"] is None and base["own"] == [] and base["free_tries"]["remaining"] == 5
    assert [m["id"] for m in base["platform"]][0] == name
    monkeypatch.setattr(llm, "listed", lambda auth: ["gpt-5", "gpt-5-mini"])
    good = client.get("/api/ai/models", headers=OWN).json()
    assert good["key_ok"] is True and [m["id"] for m in good["own"]] == ["openai:gpt-5", "openai:gpt-5-mini"]

    def reject(auth):
        raise LabError(401, "bad_key", "the AI provider rejected that key")

    monkeypatch.setattr(llm, "listed", reject)
    bad = client.get("/api/ai/models", headers=OWN)
    assert bad.json()["key_ok"] is False and KEY not in bad.text
    assert client.get("/api/ai/models", headers={"x-ai-key": KEY}).status_code == 400


def test_questionnaire_and_free_compile():
    client = make_client()
    assert [q["id"] for q in client.get("/api/ai/questionnaire").json()["questions"]] == ["family", "speed", "risk", "size"]
    body = {"symbol": SYMBOL, "interval": INTERVAL, "answers": {"family": "trend"}}
    plain = client.post("/api/ai/compile", json=body).json()
    assert plain["built_by"] == "template:trend" and plain["attempts"] == 1 and plain["rules"]
    assert plain["free_tries"] == {"limit": 5, "used": 0, "remaining": 5}
    custom = client.post("/api/ai/compile", json={**body, "answers": {"family": "dip", "speed": "fast"}}).json()
    assert custom["built_by"] == "questionnaire" and custom["spec"]["symbol"] == SYMBOL
    assert client.post("/api/ai/compile", json={**body, "answers": {"family": "nope"}}).status_code == 400
    assert client.post("/api/ai/compile", json={**body, "answers": {}}).status_code == 400
    assert client.post("/api/ai/compile", json={"symbol": "BTC", "interval": INTERVAL, "answers": {}}).status_code == 400
    assert client.post("/api/ai/compile", json={"symbol": SYMBOL, "interval": "7m"}).status_code == 400
    assert client.post("/api/ai/compile", json={"symbol": SYMBOL, "interval": INTERVAL}).status_code == 400


def test_template_route():
    client = make_client()
    out = client.get("/api/lab/templates/rsi", params={"symbol": SYMBOL, "interval": INTERVAL}).json()
    assert out["built_by"] == "template:rsi" and out["spec"]["symbol"] == SYMBOL and out["rules"]
    assert client.get("/api/lab/templates/nope", params={"symbol": SYMBOL, "interval": INTERVAL}).status_code == 404
    assert client.get("/api/lab/templates/rsi", params={"symbol": "x", "interval": INTERVAL}).status_code == 400


def test_compile_with_own_key_is_free_and_never_echoes_key(monkeypatch, caplog):
    seen = fake_chat(monkeypatch, [llm_spec(name="Mine")])
    client = make_client()
    with caplog.at_level(logging.DEBUG):
        out = client.post("/api/ai/compile", json={"steps": "buy low", "symbol": SYMBOL, "interval": INTERVAL},
                          headers=OWN)
    assert out.status_code == 200 and out.json()["built_by"] == "openai:gpt-5-mini"
    assert out.json()["free_tries"]["used"] == 0 and KEY not in out.text and KEY not in caplog.text
    assert seen[0].key == KEY
    model = client.post("/api/ai/compile", headers=OWN,
                        json={"steps": "buy low", "symbol": SYMBOL, "interval": INTERVAL, "model": "openai:gpt-5"})
    assert model.json()["built_by"] == "openai:gpt-5"
    wrong = client.post("/api/ai/compile", headers=OWN,
                        json={"steps": "x", "symbol": SYMBOL, "interval": INTERVAL, "model": "anthropic:c"})
    assert wrong.status_code == 401 and wrong.json()["code"] == "bad_key"


def test_platform_compile_spends_free_tries(monkeypatch):
    name = platform(monkeypatch)
    fake_chat(monkeypatch, [llm_spec()])
    client = make_client()
    body = {"steps": "buy low", "symbol": SYMBOL, "interval": INTERVAL, "model": name}
    for used in (1, 2, 3, 4, 5):
        out = client.post("/api/ai/compile", json=body)
        assert out.status_code == 200 and out.json()["free_tries"]["used"] == used
    assert out.json()["built_by"] == name
    spent = client.post("/api/ai/compile", json=body)
    assert spent.status_code == 429 and spent.json()["code"] == "free_tries_used"
    assert spent.json()["free_tries"]["remaining"] == 0
    free = client.post("/api/ai/compile", json={"symbol": SYMBOL, "interval": INTERVAL, "answers": {"family": "trend"}})
    assert free.status_code == 200
    other = make_client().post("/api/ai/compile", json=body)
    assert other.status_code == 200 and other.json()["free_tries"]["used"] == 1


def test_compile_retry_and_failures(monkeypatch):
    client = make_client()
    body = {"steps": "buy low", "symbol": SYMBOL, "interval": INTERVAL}
    fake_chat(monkeypatch, [llm_spec(entry="close >"), llm_spec()])
    fixed = client.post("/api/ai/compile", json=body, headers=OWN)
    assert fixed.status_code == 200 and fixed.json()["attempts"] == 2
    fake_chat(monkeypatch, [llm_spec(entry="close >")])
    broken = client.post("/api/ai/compile", json=body, headers=OWN)
    assert broken.status_code == 502 and broken.json()["code"] == "bad_output"


def test_compile_repairs_wide_param_range_without_step(monkeypatch):
    client = make_client()
    wide = {"fast": {"value": 10, "min": 2, "max": 400}, "slow": {"value": 40, "min": 20, "max": 300, "step": 1}}
    fake_chat(monkeypatch, [llm_spec(params=wide)])
    out = client.post("/api/ai/compile", headers=OWN,
                      json={"steps": "buy low", "symbol": SYMBOL, "interval": INTERVAL})
    assert out.status_code == 200 and out.json()["attempts"] == 1
    assert out.json()["spec"]["params"]["fast"]["step"] > 1


def test_ideas_and_base(monkeypatch):
    client = make_client()
    fake_chat(monkeypatch, [{"variants": [llm_spec(name="One"), llm_spec(name="Bad", entry="(("), llm_spec(name="Two")]}])
    out = client.post("/api/ai/ideas", json={"spec": spec_dict(), "steps": "variants"}, headers=OWN).json()
    assert [i["spec"]["name"] for i in out["ideas"]] == ["One", "Two"] and out["free_tries"]["used"] == 0
    bad = client.post("/api/ai/ideas", json={"spec": spec_dict(entry="("), "steps": "x"}, headers=OWN)
    assert bad.status_code == 422 and bad.json()["code"] == "invalid_spec" and bad.json()["errors"]
    fake_chat(monkeypatch, [llm_spec(name="Based")])
    based = client.post("/api/ai/compile", headers=OWN, json={"steps": "x", "symbol": SYMBOL, "interval": INTERVAL,
                                                               "base": spec_dict()})
    assert based.status_code == 200


def test_ai_routes_rate_limited(monkeypatch):
    fake_chat(monkeypatch, [llm_spec()])
    client = make_client()
    body = {"symbol": SYMBOL, "interval": INTERVAL, "answers": {"family": "trend"}}
    codes = [client.post("/api/ai/compile", json=body).status_code for _ in range(12)]
    assert codes[:10] == [200] * 10 and codes[10] == 429
    assert client.post("/api/ai/compile", json=body).json()["code"] == "rate_limited"


def test_validate_route():
    client = make_client()
    good = client.post("/api/lab/validate", json={"spec": spec_dict()}).json()
    assert good["ok"] and len(good["spec_hash"]) == 64 and good["rules"] and good["errors"] == []
    bad = client.post("/api/lab/validate", json={"spec": spec_dict(entry="nonsense(")}).json()
    assert bad["ok"] is False and bad["errors"] and bad["spec_hash"] is None
    missing = client.post("/api/lab/validate", json={"spec": {"symbol": SYMBOL}}).json()
    assert missing["ok"] is False
