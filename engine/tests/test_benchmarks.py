import json

import pytest

from agents_support import SYMBOL, INTERVAL, clean_lab, fake_chat, llm_spec, make_account, new_agent, new_version
from lab_support import fake_market
from parable import agents, benchmarks, db, proofs
from parable.errors import LabError
from parable.lab.llm import AiAuth


def collect():
    log = []
    return log, lambda fraction=None, message=None, partial=None: log.append((fraction, message, partial))


def own(provider="openai"):
    return AiAuth(provider=provider, model="m1", key="sk-secret-key")


def setup(fake_market):
    owner = make_account()
    return owner, new_agent(owner), fake_market.bars_by_code["BTCUSDT"]


def run(owner, agent, bars, models, auth=None, progress=None, steps="buy dips"):
    return benchmarks.run_benchmark(owner["id"], agent["id"], steps, models, SYMBOL, INTERVAL, bars, "market", auth,
                                    progress or (lambda *a: None), quote="USDT")


def test_model_auth_routes_keys(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "g-key")
    from parable.config import get_settings

    get_settings.cache_clear()
    auth, platform = benchmarks.model_auth("openai:gpt-5-mini", own("openai"))
    assert (auth.provider, auth.model, auth.key, platform) == ("openai", "gpt-5-mini", "sk-secret-key", False)
    auth, platform = benchmarks.model_auth("gemini:gemini-3.5-flash-lite", None)
    assert auth.provider == "platform" and platform is True
    auth, platform = benchmarks.model_auth("gemini:anything", own("gemini"))
    assert platform is False and auth.provider == "gemini"
    with pytest.raises(LabError) as err:
        benchmarks.model_auth("anthropic:claude-x", own("openai"))
    assert err.value.code == "bad_key"
    with pytest.raises(LabError) as err:
        benchmarks.model_auth("jev:gemma-4-31b-it", None)
    assert err.value.status == 503
    for bad in ("nocolon", "weird:thing"):
        with pytest.raises(LabError) as err:
            benchmarks.model_auth(bad, None)
        assert err.value.status == 400


def test_benchmark_rows_partial_and_storage(fake_market, monkeypatch):
    owner, agent, bars = setup(fake_market)
    seen = fake_chat(monkeypatch, [llm_spec(name="A"), llm_spec(name="B", entry="close >")])
    log, progress = collect()
    result = run(owner, agent, bars, ["openai:m1", "openai:m2"], own(), progress)
    assert result["id"].startswith("bm_") and len(result["rows"]) == 2
    good, bad = result["rows"]
    assert good["ok"] and good["metrics"]["total_return_pct"] is not None and good["spec"]["name"] == "A"
    assert good["built_by"] == "openai:m1" and good["rules"] and good["curve"]
    assert bad["ok"] is False and bad["error"] and bad["spec"] is None
    assert result["buy_and_hold"]["metrics"].keys() == {"total_return_pct", "max_drawdown_pct"}
    assert result["buy_and_hold"]["curve"][0][1] == 10000.0
    assert result["data"]["bars"] == len(bars) and result["data"]["quote"] == "USDT"
    partials = [p for _, _, p in log if p is not None]
    assert [len(p["rows"]) for p in partials] == [0, 1, 2]
    assert partials[1]["rows"][0]["model"] == "openai:m1"
    assert json.loads(db.one("SELECT result_json FROM benchmarks")["result_json"])["id"] == result["id"]
    assert all(a.key == "sk-secret-key" for a in seen)
    assert "sk-secret-key" not in json.dumps(result)


def test_other_provider_models_need_key(fake_market, monkeypatch):
    owner, agent, bars = setup(fake_market)
    fake_chat(monkeypatch, [llm_spec()])
    result = run(owner, agent, bars, ["openai:m1", "anthropic:claude-x", "gemini:g1"], own("openai"))
    oks = {r["model"]: r for r in result["rows"]}
    assert oks["openai:m1"]["ok"] and not oks["anthropic:claude-x"]["ok"]
    assert oks["anthropic:claude-x"]["error"] == "needs key"
    assert oks["gemini:g1"]["ok"] is False and oks["gemini:g1"]["error"]


def test_model_cap_dedupes_and_survives_failures(fake_market, monkeypatch):
    owner, agent, bars = setup(fake_market)
    fake_chat(monkeypatch, [LabError(503, "model_unavailable", "down")])
    models = [f"openai:m{i}" for i in range(9)] + ["openai:m0"]
    result = run(owner, agent, bars, models, own())
    assert len(result["rows"]) == 6 and all(not r["ok"] for r in result["rows"])
    assert result["rows"][0]["error"] == "down"


def test_adopt_saves_version_and_proof(fake_market, monkeypatch):
    owner, agent, bars = setup(fake_market)
    fake_chat(monkeypatch, [llm_spec(name="Picked", stop_loss_pct=7.0)])
    result = run(owner, agent, bars, ["openai:m1"], own())
    version = benchmarks.adopt(owner["id"], result["id"], "openai:m1")
    assert version["n"] == 1 and version["spec"]["stop_loss_pct"] == 7.0 and version["built_by"] == "openai:m1"
    assert version["steps_text"] == "buy dips"
    stored = db.one("SELECT * FROM proofs WHERE version_id = ?", (version["id"],))
    assert stored["kind"] == "benchmark" and stored["data_hash"] == result["data"]["data_hash"]
    assert benchmarks.adopt(owner["id"], result["id"], "openai:m1")["id"] == version["id"]
    with pytest.raises(LabError) as err:
        benchmarks.adopt(owner["id"], result["id"], "openai:zzz")
    assert err.value.status == 404


def test_benchmark_ownership_and_public_view(fake_market, monkeypatch):
    owner, agent, bars = setup(fake_market)
    bob = make_account("Bob")
    fake_chat(monkeypatch, [llm_spec()])
    result = run(owner, agent, bars, ["openai:m1"], own())
    assert benchmarks.benchmark_result(owner["id"], result["id"])["id"] == result["id"]
    for call in (lambda: benchmarks.benchmark_result(bob["id"], result["id"]),
                 lambda: benchmarks.adopt(bob["id"], result["id"], "openai:m1")):
        with pytest.raises(LabError) as err:
            call()
        assert err.value.status == 403
    with pytest.raises(LabError) as err:
        benchmarks.benchmark_result(owner["id"], "bm_missing")
    assert err.value.status == 404
    with pytest.raises(LabError):
        run(bob, agent, bars, ["openai:m1"], own())
    public = benchmarks.public_benchmark(result["id"])
    row = public["rows"][0]
    assert set(row) == {"model", "ok", "metrics", "curve", "spec_hash"}
    text = json.dumps(public)
    assert "entry" not in text and "summary" not in text and "buy dips" not in text
    assert benchmarks.public_benchmark("bm_missing") is None
