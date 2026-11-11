import json

import pytest

from agents_support import fake_chat, llm_spec, spec_dict, wait_job
from api_support import buy_and_approve
from conftest import sign_in
from fastapi.testclient import TestClient
from market_support import expire_run, fake_provider
from parable import ledger
from parable.db import one, rows
from parable.paypal import get_paypal
from test_spec_leak import leaks, public_dump

OWN = {"x-ai-provider": "openai", "x-ai-model": "gpt-5-mini", "x-ai-key": "sk-e2e-secret-key"}
STEPS = "buy dips in an uptrend, sell rips"


def account(client, name: str, email: str) -> TestClient:
    return sign_in(TestClient(client.app), name, email)


def new_listing(seller, version_id, proof_id, title, mode, **terms) -> dict:
    body = {"version_id": version_id, "title": title, "pitch": "End to end.", "price_cents": 2000, "mode": mode,
            "trial_s": 120, "min_return_bps": -50, "max_loss_bps": 1000, "proof_id": proof_id,
            "allow_test_drive": True, **terms}
    created = seller.post("/api/listings", json=body)
    assert created.status_code == 200, created.text
    return created.json()


def wait_status(buyer, purchase_id, wait_until, statuses) -> dict:
    assert wait_until(lambda: buyer.get(f"/api/purchases/{purchase_id}").json()["status"] in statuses)
    return buyer.get(f"/api/purchases/{purchase_id}").json()


def seq_of(kind: str, purchase_id: str) -> int:
    return next(e["seq"] for e in ledger.entries(subject=f"purchase:{purchase_id}") if e["kind"] == kind)


@pytest.fixture
def world(client, manager):
    fake_provider()
    return {"ada": account(client, "Ada Creator", "ada@e2e.test"), "bob": account(client, "Bob Buyer", "bob@e2e.test"),
            "cara": account(client, "Cara Buyer", "cara@e2e.test"), "anon": TestClient(client.app), "client": client}


def build_agents(world, monkeypatch, wait_until) -> dict:
    ada = world["ada"]
    agent = ada.post("/api/agents", json={"name": "E2E Trend", "symbol": "fake:BTCUSDT", "interval": "1h"}).json()
    base = f"/api/agents/{agent['id']}"
    spec = spec_dict()
    assert ada.post("/api/lab/validate", json={"spec": spec}).json()["ok"] is True
    tested = ada.post("/api/lab/backtest", json={"spec": spec, "limit": 400}).json()
    assert tested["metrics"]["trades"] > 0 and tested["trades"] and tested["markers"]
    v1 = ada.post(f"{base}/versions", json={"spec": spec, "steps_text": STEPS, "built_by": "template:trend"}).json()
    proof1 = ada.post(f"{base}/versions/{v1['id']}/backtest", json={"limit": 400}).json()
    assert proof1["kind"] == "backtest" and proof1["trades"] and proof1["result_hash"] == tested["result_hash"]
    fake_chat(monkeypatch, [llm_spec(name="Second", stop_loss_pct=9.0), llm_spec(name="Third", stop_loss_pct=4.0)])
    started = ada.post(f"{base}/benchmark", json={"steps": STEPS, "models": ["openai:m1", "openai:m2"], "limit": 400},
                       headers=OWN)
    bench = wait_job(ada, started.json()["job_id"], wait_until)["result"]
    assert [row["ok"] for row in bench["rows"]] == [True, True]
    v2 = ada.post(f"/api/benchmarks/{bench['id']}/adopt", json={"model": "openai:m1"}).json()
    proof2 = ada.post(f"{base}/versions/{v2['id']}/backtest", json={"limit": 400}).json()
    opt = ada.post("/api/lab/optimize", json={"spec": spec, "limit": 400, "top_k": 3}).json()
    assert wait_job(ada, opt["job_id"], wait_until)["status"] == "done"
    return {"v1": v1, "v2": v2, "proof1": proof1, "proof2": proof2, "bench": bench,
            "specs": [spec, v2["spec"]]}


def test_full_marketplace_flow(world, monkeypatch, wait_until):
    ada, bob, cara, anon = world["ada"], world["bob"], world["cara"], world["anon"]
    built = build_agents(world, monkeypatch, wait_until)
    hold = new_listing(ada, built["v1"]["id"], built["proof1"]["id"], "E2E Hold", "hold")
    instant = new_listing(ada, built["v2"]["id"], built["proof2"]["id"], "E2E Instant", "instant")
    losing = new_listing(ada, built["v1"]["id"], built["proof1"]["id"], "E2E Hold Fail", "hold", min_return_bps=500)
    assert ada.post(f"/api/listings/{instant['id']}/benchmark", json={"benchmark_id": built["bench"]["id"]}
                    ).json()["benchmark"]["rows"][0]["model"] == "openai:m1"
    assert hold["track"]["status"] == "alive" and instant["track"]["runs_total"] == 1

    rerun = bob.post(f"/api/listings/{hold['id']}/rerun", json={}).json()
    assert rerun["match"] is True and rerun["rerun"]["result_hash"] == rerun["claim"]["result_hash"]
    assert rerun["rerun"]["by"] == "visitor" and anon.get(f"/api/listings/{hold['id']}").json()["reruns"] == {
        "count": 1, "matched": 1}
    drive = bob.post(f"/api/listings/{hold['id']}/test-drive", json={"symbol": "fake:ETHUSDT"}).json()
    assert drive["proof"]["kind"] == "testdrive" and drive["proof"]["data"]["symbol"] == "fake:ETHUSDT"

    won = buy_and_approve(bob, hold["id"])
    live = bob.get(f"/api/purchases/{won['purchase_id']}").json()
    assert live["status"] == "probation" and live["mode"] == "hold" and live["run"]["purpose"] == "probation"
    expire_run(live["run"]["id"])
    paid = wait_status(bob, won["purchase_id"], wait_until, ("paid_out", "error"))
    assert paid["status"] == "paid_out" and paid["license"]["spec"]["entry"] and paid["verdict"]["passed"]
    assert seq_of("payment.captured", won["purchase_id"]) < seq_of("payout.sent", won["purchase_id"])

    lost = buy_and_approve(bob, losing["id"])
    expire_run(bob.get(f"/api/purchases/{lost['purchase_id']}").json()["run"]["id"])
    voided = wait_status(bob, lost["purchase_id"], wait_until, ("voided", "error"))
    assert voided["status"] == "voided" and voided["license"] is None and voided["paypal_capture_id"] == ""

    get_paypal().fail_next("create_payout", "PAYOUT_DOWN")
    bought = buy_and_approve(cara, instant["id"])
    failing = cara.get(f"/api/purchases/{bought['purchase_id']}").json()
    assert failing["status"] == "error" and failing["paypal_capture_id"] and failing["license"]["key"]
    captured_at = seq_of("payment.captured", bought["purchase_id"])
    done = cara.post(f"/api/purchases/{bought['purchase_id']}/retry").json()
    assert done["status"] == "paid_out" and done["paypal_capture_id"] == failing["paypal_capture_id"]
    assert seq_of("payment.captured", bought["purchase_id"]) == captured_at < seq_of("payout.sent",
                                                                                      bought["purchase_id"])
    assert [e["kind"] for e in ledger.entries(subject=f"purchase:{bought['purchase_id']}")].count(
        "payment.captured") == 1

    download = cara.get(f"/api/purchases/{bought['purchase_id']}/license")
    assert download.status_code == 200 and "attachment" in download.headers["content-disposition"]
    assert download.json()["spec_hash"] == built["v2"]["spec_hash"]
    ran = cara.post(f"/api/purchases/{bought['purchase_id']}/run", json={"start_cash": 1000})
    assert ran.status_code == 200 and ran.json()["purpose"] == "practice"
    assert bob.get(f"/api/purchases/{bought['purchase_id']}").status_code == 404

    own = ada.post("/api/purchases", json={"listing_id": hold["id"]})
    assert own.status_code == 403 and own.json()["code"] == "self_purchase"
    ada_payer = one("SELECT paypal_payer_id FROM sellers WHERE email = ?", ("ada@e2e.test",))["paypal_payer_id"]
    sneaky = cara.post("/api/purchases", json={"listing_id": instant["id"]}).json()
    get_paypal().approve(sneaky["paypal_order_id"], payer_id=ada_payer)
    cara.get(f"/paypal/return?token={sneaky['paypal_order_id']}&purchase={sneaky['purchase_id']}")
    assert cara.get(f"/api/purchases/{sneaky['purchase_id']}").json()["status"] == "cancelled"
    assert get_paypal().get_order(sneaky["paypal_order_id"])["status"] == "APPROVED"

    mine = ada.get("/api/me/sales").json()
    assert {sale["title"] for sale in mine} == {"E2E Hold", "E2E Instant", "E2E Hold Fail"}
    assert bob.get("/api/me/agents").json()["bought"] and ada.get("/api/me/agents").json()["built"][0]["status"] == "listed"

    ids = [hold["id"], instant["id"], losing["id"]]
    paths = [f"/api/listings/{i}" for i in ids] + [f"/api/proofs/{built['proof1']['id']}", "/api/runs"]
    paths += [f"/api/runs/{live['run']['id']}", f"/api/runs/{live['run']['id']}/points",
              f"/api/sellers/{hold['seller']['id']}", f"/api/listings/{hold['id']}/diligence"]
    text = public_dump(anon, paths)
    for spec in built["specs"]:
        assert leaks(text, spec, STEPS) == []
    purchase_text = json.dumps({**paid, "license": None}) + json.dumps({**voided})
    assert all(not leaks(purchase_text, spec, STEPS) for spec in built["specs"])
    assert all(row["data_json"] and not leaks(row["data_json"], built["specs"][0], STEPS)
               for row in rows("SELECT data_json FROM ledger"))

    assert anon.get("/api/ledger/verify").json()["ok"] is True
    tamper = anon.post("/api/ledger/tamper-demo").json()
    assert tamper["verify"]["ok"] is False and anon.get("/api/ledger/verify").json()["ok"] is True
