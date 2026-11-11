import logging

import pytest

from agents_support import (INTERVAL, SYMBOL, clean_lab, csv_file, daily_csv, fake_chat, llm_spec, make_account,
                            make_client, spec_dict, wait_job)
from lab_support import fake_market, make_bars
from parable.config import get_settings
from parable.errors import LabError
from parable.lab import datasets, llm, markets, quota

KEY = "sk-very-secret-key"
OWN = {"x-ai-provider": "openai", "x-ai-model": "gpt-5-mini", "x-ai-key": KEY}


def upload(client, content=None, name="Mine"):
    files = {"file": ("prices.csv", content or daily_csv(), "text/csv")}
    return client.post("/api/datasets", files=files, data={"name": name, "quote": "INR"})


def test_markets_basic(fake_market):
    client = make_client()
    popular = client.get("/api/markets/popular?kind=crypto").json()
    assert popular and "symbol" in popular[0]
    found = client.get("/api/markets/search", params={"q": "btc"}).json()
    assert any(i["symbol"] == SYMBOL for i in found)
    candles = client.get("/api/markets/candles", params={"symbol": SYMBOL, "interval": INTERVAL, "limit": 50}).json()
    assert len(candles["bars"]) == 50 and candles["quote"] == "USDT" and candles["source_kind"] == "market"
    assert len(candles["data_hash"]) == 64
    quote = client.get("/api/markets/latest", params={"symbol": SYMBOL}).json()
    assert quote["price"] == 100.0 and quote["stale"] is False
    big = client.get("/api/markets/candles", params={"symbol": SYMBOL, "interval": INTERVAL, "limit": 5001})
    assert big.status_code == 400 and big.json()["code"] == "bad_request"
    assert client.get("/api/markets/candles", params={"symbol": "fake:NOPE", "interval": INTERVAL}).status_code == 404


def test_search_is_rate_limited(fake_market):
    client = make_client()
    codes = {client.get("/api/markets/search", params={"q": "b"}).status_code for _ in range(62)}
    assert 429 in codes


def test_upload_symbols_never_leak_across_accounts(fake_market):
    ada, bob = make_account("Ada"), make_account("Bob")
    owner, other, anon = make_client(ada), make_client(bob), make_client()
    stored = upload(owner).json()["dataset"]
    symbol = stored["symbol"]
    query = {"symbol": symbol, "interval": "1d"}
    assert len(owner.get("/api/markets/candles", params=query).json()["bars"]) == 60
    assert owner.get("/api/markets/latest", params={"symbol": symbol}).json()["quote"] == "INR"
    assert other.get("/api/markets/candles", params=query).status_code == 403
    assert other.get("/api/markets/latest", params={"symbol": symbol}).status_code == 403
    assert anon.get("/api/markets/candles", params=query).status_code == 401
    assert anon.get("/api/markets/latest", params={"symbol": symbol}).status_code == 401
    for client in (owner, other, anon):
        names = {i["symbol"] for i in client.get("/api/markets/search", params={"q": "Mine"}).json()}
        names |= {i["symbol"] for i in client.get("/api/markets/popular", params={"kind": "mine"}).json()}
        assert symbol not in names
    assert other.get("/api/markets/candles", params=query).status_code == 403


def test_upload_bars_not_reachable_through_market_layer():
    ada = make_account("Ada")
    stored = datasets.store_dataset(ada["id"], "Mine", "USD", make_bars(40, interval_s=86400), "1d")
    for call in (lambda: markets.candles(stored["symbol"], "1d", 10), lambda: markets.latest(stored["symbol"]),
                 lambda: markets.symbol_info(stored["symbol"])):
        with pytest.raises(LabError):
            call()
        with pytest.raises(LabError):
            call()
    assert not hasattr(datasets, "raw_dataset")


def test_dataset_upload_list_get_delete_and_idor():
    ada, bob = make_account("Ada"), make_account("Bob")
    owner, other, anon = make_client(ada), make_client(bob), make_client()
    done = upload(owner).json()
    assert done["status"] == "ready" and done["dataset"]["interval"] == "1d" and "bars" not in done["dataset"]
    dataset_id = done["dataset"]["id"]
    assert owner.get("/api/datasets").json()[0]["bar_count"] == 60 and other.get("/api/datasets").json() == []
    one = owner.get(f"/api/datasets/{dataset_id}").json()
    assert one["name"] == "Mine" and one["bar_count"] == 60
    assert other.get(f"/api/datasets/{dataset_id}").status_code == 403
    assert other.delete(f"/api/datasets/{dataset_id}").status_code == 403
    assert anon.get(f"/api/datasets/{dataset_id}").status_code == 401
    assert owner.get("/api/datasets/d_missing000").status_code == 404
    assert owner.delete(f"/api/datasets/{dataset_id}").json() == {"ok": True}
    assert owner.get(f"/api/datasets/{dataset_id}").status_code == 404


def test_dataset_upload_requires_signin_and_limits_size(monkeypatch):
    assert upload(make_client()).status_code == 401
    monkeypatch.setenv("UPLOAD_MAX_BYTES", "100")
    get_settings.cache_clear()
    big = upload(make_client(make_account()), daily_csv())
    assert big.status_code == 413 and big.json()["code"] == "too_large"


def test_dataset_mapping_flow_and_draft_idor(monkeypatch):
    ada, bob = make_account("Ada"), make_account("Bob")
    owner, other = make_client(ada), make_client(bob)
    odd = ("when,px\n" + "\n".join(f"{1_700_000_000 + i * 86400},{10 + i}" for i in range(60))).encode()
    first = upload(owner, odd).json()
    assert first["status"] == "needs_mapping" and first["columns"] == ["when", "px"] and first["suggestion"] is None
    draft = first["draft_id"]
    body = {"draft_id": draft, "mapping": {"t": "when", "close": "px"}, "name": "Odd", "quote": "usd"}
    assert other.post("/api/datasets/map", json=body).status_code == 403
    assert other.post("/api/datasets/ai-map", json={"draft_id": draft}, headers=OWN).status_code == 403
    done = owner.post("/api/datasets/map", json=body).json()
    assert done["status"] == "ready" and done["dataset"]["name"] == "Odd" and done["dataset"]["quote"] == "USD"
    assert owner.post("/api/datasets/map", json=body).status_code == 200
    bad = owner.post("/api/datasets/map", json={**body, "draft_id": "dr_nothere00"})
    assert bad.status_code == 404


def test_dataset_ai_map_uses_own_key_without_tries(monkeypatch):
    owner = make_client(make_account("Ada"))
    odd = ("when,px\n" + "\n".join(f"{1_700_000_000 + i * 86400},{10 + i}" for i in range(60))).encode()
    draft = upload(owner, odd).json()["draft_id"]
    fake_chat(monkeypatch, [{"t": "when", "close": "px"}])
    mapped = owner.post("/api/datasets/ai-map", json={"draft_id": draft}, headers=OWN)
    assert mapped.status_code == 200 and mapped.json()["mapping"]["t"] == "when"
    assert mapped.json()["by"] == "openai:gpt-5-mini" and KEY not in mapped.text
    assert quota.free_tries(make_account("Ada")["id"])["used"] == 0
    assert owner.post("/api/datasets/ai-map", json={"draft_id": draft}).status_code == 503


def test_backtest_route(fake_market):
    client = make_client()
    out = client.post("/api/lab/backtest", json={"spec": spec_dict(), "limit": 400})
    result = out.json()
    assert out.status_code == 200 and result["data"]["bars"] == 400 and "trades" in result and "markers" in result
    assert result["data"]["symbol"] == SYMBOL and result["result_hash"]
    again = client.post("/api/lab/backtest", json={"spec": spec_dict(), "limit": 400}).json()
    assert again["result_hash"] == result["result_hash"]
    invalid = client.post("/api/lab/backtest", json={"spec": spec_dict(entry="x +")})
    assert invalid.status_code == 422 and invalid.json()["code"] == "invalid_spec"
    short = client.post("/api/lab/backtest", json={"spec": spec_dict(), "limit": 5})
    assert short.status_code == 400
    assert client.post("/api/lab/backtest", json={"spec": spec_dict(), "symbol": "fake:NOPE"}).status_code == 404


def test_backtest_on_own_dataset_and_idor(fake_market):
    ada, bob = make_account("Ada"), make_account("Bob")
    owner, other, anon = make_client(ada), make_client(bob), make_client()
    dataset = upload(owner, daily_csv(120)).json()["dataset"]
    body = {"spec": spec_dict(interval="1d"), "dataset_id": dataset["id"]}
    ran = owner.post("/api/lab/backtest", json=body)
    assert ran.status_code == 200 and ran.json()["data"]["source_kind"] == "creator"
    assert ran.json()["data"]["symbol"] == dataset["symbol"] and ran.json()["data"]["quote"] == "INR"
    assert other.post("/api/lab/backtest", json=body).status_code == 403
    assert anon.post("/api/lab/backtest", json=body).status_code == 401
    by_symbol = {"spec": spec_dict(interval="1d", symbol=dataset["symbol"])}
    assert other.post("/api/lab/backtest", json=by_symbol).status_code == 403
    assert other.post("/api/lab/optimize", json=body).status_code == 403
    assert owner.post("/api/lab/backtest", json=by_symbol).status_code == 200


def test_backtest_rate_limit(fake_market, monkeypatch):
    monkeypatch.setenv("RATE_LAB_PER_MINUTE", "2")
    get_settings.cache_clear()
    client = make_client()
    codes = [client.post("/api/lab/backtest", json={"spec": spec_dict(), "limit": 300}).status_code for _ in range(3)]
    assert codes == [200, 200, 429]


def test_optimize_job_flow_and_job_idor(fake_market, wait_until):
    client, other = make_client(), make_client()
    started = client.post("/api/lab/optimize", json={"spec": spec_dict(), "top_k": 3})
    assert started.status_code == 200
    job_id = started.json()["job_id"]
    assert other.get(f"/api/jobs/{job_id}").status_code == 404
    done = wait_job(client, job_id, wait_until)
    assert done["status"] == "done" and done["progress"] == 1.0 and done["kind"] == "optimize"
    assert 1 <= len(done["result"]["rows"]) <= 3 and "base" in done["result"]
    assert client.get("/api/jobs/j_missing000").status_code == 404


def test_optimize_publishes_partial_results(fake_market, monkeypatch):
    import threading

    from parable.lab import optimize as opt

    gate = threading.Event()
    real = opt.quick_metrics
    calls = {"n": 0}

    def slow(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] > 25:
            gate.wait(5)
        return real(*args, **kwargs)

    monkeypatch.setattr(opt, "quick_metrics", slow)
    client = make_client()
    job_id = client.post("/api/lab/optimize", json={"spec": spec_dict()}).json()["job_id"]
    import time

    deadline = time.time() + 5
    partial = None
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] == "running" and job["result"] is not None:
            partial = job
            break
        time.sleep(0.01)
    gate.set()
    assert partial is not None and partial["result"]["evaluated"] >= 0 and "rows" in partial["result"]


def test_optimize_rate_limit_and_job_cap(fake_market):
    client = make_client()
    codes = [client.post("/api/lab/optimize", json={"spec": spec_dict()}).status_code for _ in range(7)]
    assert 429 in codes

