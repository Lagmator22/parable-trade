import json

import pytest

from agents_support import (INTERVAL, SYMBOL, add_listing, clean_lab, daily_csv, fake_chat, llm_spec, make_account,
                            make_client, new_agent, new_version, spec_dict, wait_job)
from lab_support import fake_market
from parable import db, ledger, proofs
from parable.config import get_settings

KEY = "sk-very-secret-key"
OWN = {"x-ai-provider": "openai", "x-ai-model": "gpt-5-mini", "x-ai-key": KEY}


@pytest.fixture
def pair():
    ada, bob = make_account("Ada"), make_account("Bob")
    return ada, bob, make_client(ada), make_client(bob), make_client()


def test_agent_crud_and_idor(pair):
    ada, bob, owner, other, anon = pair
    created = owner.post("/api/agents", json={"name": "Alpha", "symbol": SYMBOL, "interval": INTERVAL})
    assert created.status_code == 200
    agent = created.json()
    assert agent["status"] == "draft" and agent["versions"] == [] and "owner_id" not in agent
    assert owner.get("/api/agents").json()[0]["id"] == agent["id"] and other.get("/api/agents").json() == []
    assert owner.get(f"/api/agents/{agent['id']}").json()["name"] == "Alpha"
    assert other.get(f"/api/agents/{agent['id']}").status_code == 403
    assert other.delete(f"/api/agents/{agent['id']}").status_code == 403
    assert anon.get(f"/api/agents/{agent['id']}").status_code == 401
    assert anon.get("/api/agents").status_code == 401
    assert anon.post("/api/agents", json={"name": "x", "symbol": SYMBOL, "interval": INTERVAL}).status_code == 401
    assert owner.get("/api/agents/a_missing000").status_code == 404
    bad = owner.post("/api/agents", json={"name": "x", "symbol": "BTC", "interval": INTERVAL})
    assert bad.status_code == 400 and bad.json()["code"] == "bad_request"
    assert owner.delete(f"/api/agents/{agent['id']}").json() == {"ok": True}
    assert owner.get(f"/api/agents/{agent['id']}").status_code == 404


def test_versions_routes_and_idor(pair):
    ada, bob, owner, other, anon = pair
    agent = owner.post("/api/agents", json={"name": "A", "symbol": SYMBOL, "interval": INTERVAL}).json()
    path = f"/api/agents/{agent['id']}/versions"
    saved = owner.post(path, json={"spec": spec_dict(), "steps_text": "buy dips", "built_by": "template:trend"})
    version = saved.json()
    assert saved.status_code == 200 and version["n"] == 1 and version["spec"]["entry"] and version["built_by"] == "template:trend"
    assert owner.post(path, json={"spec": spec_dict()}).json()["id"] == version["id"]
    detail = owner.get(f"/api/agents/{agent['id']}").json()
    assert len(detail["versions"]) == 1 and "spec" not in detail["versions"][0]
    assert version["spec"]["entry"] not in json.dumps(detail)
    assert owner.get(f"{path}/{version['id']}").json()["spec"]["entry"] == version["spec"]["entry"]
    assert other.post(path, json={"spec": spec_dict()}).status_code == 403
    assert other.get(f"{path}/{version['id']}").status_code == 403
    assert anon.get(f"{path}/{version['id']}").status_code == 401
    assert owner.get(f"{path}/v_missing000").status_code == 404
    invalid = owner.post(path, json={"spec": spec_dict(entry="(((")})
    assert invalid.status_code == 422 and invalid.json()["code"] == "invalid_spec" and invalid.json()["errors"]
    mine = owner.post("/api/agents", json={"name": "B", "symbol": SYMBOL, "interval": INTERVAL}).json()
    assert owner.get(f"/api/agents/{mine['id']}/versions/{version['id']}").status_code == 404


def test_version_backtest_stores_owner_proof(fake_market, pair):
    ada, bob, owner, other, anon = pair
    agent = new_agent(ada)
    version = new_version(ada, agent)
    path = f"/api/agents/{agent['id']}/versions/{version['id']}/backtest"
    ran = owner.post(path, json={"limit": 400})
    proof = ran.json()
    assert ran.status_code == 200 and proof["kind"] == "backtest" and proof["trades_count"] == len(proof["trades"])
    assert proof["version_id"] == version["id"] and proof["ledger_seq"] and proof["markers"] is not None
    assert ledger.entries(subject=f"proof:{proof['id']}")[0]["kind"] == "proof.stored"
    assert other.post(path, json={}).status_code == 403
    assert anon.post(path, json={}).status_code == 401
    wrong = other.post(f"/api/agents/{agent['id']}/versions/v_other00000/backtest", json={})
    assert wrong.status_code in (403, 404)
    assert owner.post(path, json={"symbol": "fake:NOPE"}).status_code == 404


def test_proof_route_visibility(fake_market, pair):
    ada, bob, owner, other, anon = pair
    agent = new_agent(ada)
    version = new_version(ada, agent)
    proof = owner.post(f"/api/agents/{agent['id']}/versions/{version['id']}/backtest", json={"limit": 400}).json()
    seen = owner.get(f"/api/proofs/{proof['id']}").json()
    assert "trades" in seen and seen["by"] == "seller"
    assert other.get(f"/api/proofs/{proof['id']}").status_code == 404
    assert anon.get(f"/api/proofs/{proof['id']}").status_code == 404
    listing = add_listing(ada, version["id"], proof["id"])
    for viewer in (other, anon):
        public = viewer.get(f"/api/proofs/{proof['id']}")
        assert public.status_code == 200
        body = public.json()
        assert "trades" not in body and "markers" not in body and "version_id" not in body
        assert version["spec"]["entry"] not in public.text
    db.execute("UPDATE listings SET active = 0 WHERE id = ?", (listing,))
    assert other.get(f"/api/proofs/{proof['id']}").status_code == 404
    assert owner.get("/api/proofs/pf_missing000").status_code == 404


def test_practice_run_start_and_public_views(fake_market, pair):
    ada, bob, owner, other, anon = pair
    agent = new_agent(ada)
    version = new_version(ada, agent)
    path = f"/api/agents/{agent['id']}/versions/{version['id']}/run"
    started = owner.post(path, json={"start_cash": 5000, "max_loss_bps": 500})
    run = started.json()
    assert started.status_code == 200 and run["purpose"] == "practice" and run["status"] == "alive"
    assert run["start_cash_usd"] == 5000 * 10**6 and run["quote"] == "USDT" and run["symbol"] == SYMBOL
    assert "rules" not in run and "rules_json" not in run and "version_id" not in run
    assert anon.get(f"/api/runs/{run['id']}").status_code == 404
    assert other.get(f"/api/runs/{run['id']}").status_code == 404
    assert anon.get("/api/runs").json() == []
    assert anon.get(f"/api/runs/{run['id']}/points").status_code == 404
    mine = owner.get(f"/api/runs/{run['id']}").json()
    assert "rules" not in mine and "version_id" not in mine and version["spec"]["entry"] not in json.dumps(mine)
    listed = owner.get("/api/runs").json()
    assert listed and all("version_id" not in r and "rules" not in r for r in listed)
    assert other.post(path, json={}).status_code == 403
    assert anon.post(path, json={}).status_code == 401
    assert owner.post(path, json={"start_cash": -5}).status_code == 422
    points = owner.get(f"/api/runs/{run['id']}/points").json()
    assert points["run_id"] == run["id"] and points["quote"] == "USDT" and points["start_cash"] == 5000 * 10**6
    assert isinstance(points["points"], list)
    assert other.post(f"/api/runs/{run['id']}/stop").status_code == 403
    assert anon.post(f"/api/runs/{run['id']}/stop").status_code == 401
    stopped = owner.post(f"/api/runs/{run['id']}/stop").json()
    assert stopped["status"] == "dead" and stopped["cause"] == "stopped"
    assert anon.get("/api/runs/99999/points").status_code == 404


def test_practice_run_refuses_uploaded_data(fake_market, pair):
    ada, bob, owner, other, anon = pair
    stored = owner.post("/api/datasets", files={"file": ("a.csv", daily_csv(), "text/csv")}).json()["dataset"]
    agent = new_agent(ada)
    version = new_version(ada, agent, symbol=stored["symbol"], interval="1d")
    resp = owner.post(f"/api/agents/{agent['id']}/versions/{version['id']}/run", json={})
    assert resp.status_code == 400


def test_run_points_and_ledger_routes(fake_market, pair):
    ada, bob, owner, other, anon = pair
    agent = new_agent(ada)
    version = new_version(ada, agent)
    run = owner.post(f"/api/agents/{agent['id']}/versions/{version['id']}/run", json={}).json()
    entries = anon.get("/api/ledger", params={"subject": f"run:{run['id']}"}).json()
    assert entries and version["spec"]["entry"] not in json.dumps(entries)
    assert anon.get("/api/ledger/verify").json()["ok"] is True


def test_benchmark_job_flow_and_idor(fake_market, monkeypatch, wait_until, pair):
    ada, bob, owner, other, anon = pair
    agent = new_agent(ada)
    new_version(ada, agent)
    fake_chat(monkeypatch, [llm_spec(name="First"), llm_spec(name="Second", stop_loss_pct=9.0)])
    path = f"/api/agents/{agent['id']}/benchmark"
    body = {"models": ["openai:m1", "openai:m2"], "limit": 400}
    assert other.post(path, json=body, headers=OWN).status_code == 403
    assert anon.post(path, json=body).status_code == 401
    started = owner.post(path, json=body, headers=OWN)
    assert started.status_code == 200 and started.json()["free_tries"]["used"] == 0
    job = wait_job(owner, started.json()["job_id"], wait_until)
    assert job["status"] == "done" and job["kind"] == "benchmark" and KEY not in json.dumps(job)
    result = job["result"]
    assert len(result["rows"]) == 2 and all(r["ok"] for r in result["rows"])
    assert other.get(f"/api/jobs/{started.json()['job_id']}").status_code == 404
    fetched = owner.get(f"/api/benchmarks/{result['id']}")
    assert fetched.status_code == 200 and fetched.json()["id"] == result["id"]
    assert other.get(f"/api/benchmarks/{result['id']}").status_code == 403
    assert anon.get(f"/api/benchmarks/{result['id']}").status_code == 401
    assert owner.get("/api/benchmarks/bm_missing000").status_code == 404
    adopt = f"/api/benchmarks/{result['id']}/adopt"
    assert other.post(adopt, json={"model": "openai:m2"}).status_code == 403
    assert owner.post(adopt, json={"model": "openai:zzz"}).status_code == 404
    version = owner.post(adopt, json={"model": "openai:m2"}).json()
    assert version["spec"]["stop_loss_pct"] == 9.0 and version["n"] == 2 and version["built_by"] == "openai:m2"


def test_benchmark_needs_steps_and_platform_tries(fake_market, monkeypatch, wait_until, pair):
    ada, bob, owner, other, anon = pair
    agent = new_agent(ada)
    path = f"/api/agents/{agent['id']}/benchmark"
    assert owner.post(path, json={"models": ["openai:m1"]}, headers=OWN).status_code == 400
    monkeypatch.setenv("GEMINI_API_KEY", "g-platform")
    monkeypatch.setenv("GEMINI_MODELS", "gemini-a,gemini-b,gemini-c")
    monkeypatch.setenv("AI_FREE_TRIES_PER_DAY", "3")
    get_settings.cache_clear()
    fake_chat(monkeypatch, [llm_spec()])
    models = ["gemini:gemini-a", "gemini:gemini-b", "gemini:gemini-c"]
    started = owner.post(path, json={"models": models, "steps": "buy dips", "limit": 400})
    assert started.status_code == 200 and started.json()["free_tries"]["remaining"] == 0
    wait_job(owner, started.json()["job_id"], wait_until)
    spent = owner.post(path, json={"models": models[:1], "steps": "buy dips", "limit": 400})
    assert spent.status_code == 429 and spent.json()["code"] == "free_tries_used"


def test_benchmark_defaults_to_latest_version_steps(fake_market, monkeypatch, wait_until, pair):
    ada, bob, owner, other, anon = pair
    agent = new_agent(ada)
    new_version(ada, agent)
    fake_chat(monkeypatch, [llm_spec()])
    started = owner.post(f"/api/agents/{agent['id']}/benchmark", json={"models": ["openai:m1"], "limit": 400},
                         headers=OWN)
    assert started.status_code == 200
    assert wait_job(owner, started.json()["job_id"], wait_until)["result"]["rows"][0]["ok"]
    stored = db.one("SELECT steps_text FROM benchmarks")
    assert stored["steps_text"] == "buy dips"


def test_benchmark_on_foreign_dataset_is_refused(fake_market, pair):
    ada, bob, owner, other, anon = pair
    stored = other.post("/api/datasets", files={"file": ("a.csv", daily_csv(), "text/csv")}).json()["dataset"]
    agent = new_agent(ada)
    resp = owner.post(f"/api/agents/{agent['id']}/benchmark", json={"models": ["openai:m1"], "steps": "x",
                                                                    "dataset_id": stored["id"]}, headers=OWN)
    assert resp.status_code == 403
    version = new_version(ada, agent)
    back = owner.post(f"/api/agents/{agent['id']}/versions/{version['id']}/backtest", json={"dataset_id": stored["id"]})
    assert back.status_code == 403


def test_public_run_views_stay_clean_for_legacy_rows(pair):
    anon = pair[4]
    assert anon.get("/api/runs").json() == []


def test_stop_run_without_sign_in_has_a_code(client):
    response = client.post("/api/runs/1/stop")
    assert response.status_code == 401 and response.json()["code"] == "unauthorized"
