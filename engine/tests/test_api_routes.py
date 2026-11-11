from fastapi import APIRouter
from fastapi.testclient import TestClient

from api_support import buy_and_approve
from market_support import expire_run, make_listing
from parable import api, market, referee
from parable.db import one
from parable.paypal import PayPalError, get_paypal
from parable.referee import RefereeError


def flow_seller() -> dict:
    return one("SELECT id FROM sellers WHERE email = ?", ("flow@example.com",))


def listing_for_sale(**options) -> dict:
    return make_listing(flow_seller(), mode=options.pop("mode", "instant"), **options)


def test_info_describes_the_deployment(client):
    info = client.get("/api/info").json()
    assert info["paypal_mode"] == "mock" and info["paypal_client_id"] == "" and info["currency"] == "USD"
    assert info["platform_fee_bps"] == 1000 and info["analyst"] == "rules"
    assert "eth_price_usd" not in info and "strategies" not in info and "brains" not in info
    assert info["kinds"] == ["crypto", "stocks", "funds", "forex", "gold", "mine"]
    assert "1s" in info["intervals"] and "1d" in info["intervals"]
    assert {template["id"] for template in info["templates"]} >= {"trend", "rsi", "bollinger"}
    assert info["limits"]["min_bars"] == 30 and info["limits"]["upload_max_bytes"] == 5_000_000
    assert info["ai"] == {"free_tries_per_day": 5} and info["ledger_head"]["seq"] >= 0
    assert client.get("/api/prices").status_code == 404


def test_stats_have_no_eth_fields_and_count_the_lab(client):
    stats = client.get("/api/stats").json()
    assert {"agents", "proofs", "reruns", "listings", "ledger_head"} <= set(stats)
    assert not any("eth" in key for key in stats)


def test_listing_routes_and_validation(seller_client, manager):
    listing = listing_for_sale()
    detail = seller_client.get(f"/api/listings/{listing['id']}").json()
    assert detail["id"] == listing["id"] and detail["recent_runs"][0]["purpose"] == "track"
    assert [item["id"] for item in seller_client.get("/api/listings").json()] == [listing["id"]]
    body = {"version_id": listing["version_id"], "title": "Again", "price_cents": 5, "proof_id": listing["proof_id"]}
    invalid = seller_client.post("/api/listings", json=body)
    assert invalid.status_code == 422 and invalid.json()["detail"].startswith("price_cents")
    bad_proof = seller_client.post("/api/listings", json={**body, "price_cents": 500, "proof_id": "pf_nope"})
    assert bad_proof.status_code == 400 and bad_proof.json()["code"] == "bad_request"
    assert seller_client.get("/api/listings/l_unknown").status_code == 404
    paused = seller_client.post(f"/api/listings/{listing['id']}/pause").json()
    assert paused["active"] is False and seller_client.get("/api/listings").json() == []


def test_only_the_owner_can_pause_resume_or_attach(seller_client, buyer_client, manager):
    listing = listing_for_sale()
    for action in ("pause", "resume"):
        assert buyer_client.post(f"/api/listings/{listing['id']}/{action}").status_code == 403
    assert buyer_client.post(f"/api/listings/{listing['id']}/benchmark", json={"benchmark_id": "bm_x"}
                             ).status_code == 403
    seller_client.post("/api/logout")
    assert seller_client.post(f"/api/listings/{listing['id']}/pause").status_code == 401


def test_seller_profile(seller_client, manager):
    seller = seller_client.get("/api/me").json()["seller"]
    listing_for_sale()
    profile = seller_client.get(f"/api/sellers/{seller['id']}").json()
    assert profile["seller"]["name"] == "Flow Seller" and profile["record"]["track_runs"] == 1
    assert len(profile["listings"]) == 1 and profile["listings"][0]["headline"]
    assert seller_client.get("/api/sellers/s_missing").status_code == 404


def test_diligence_and_shopper_endpoints(seller_client, manager):
    listing = listing_for_sale()
    report = seller_client.get(f"/api/listings/{listing['id']}/diligence").json()
    assert report["risk"] in ("low", "medium", "high") and report["by"] == "rules"
    assert seller_client.get("/api/listings/l_nope/diligence").status_code == 404
    answer = seller_client.post("/api/shopper", json={"query": "a cheap agent", "budget_cents": 5000}).json()
    assert answer["listing_id"] == listing["id"] and answer["listing"]["id"] == listing["id"]
    empty = seller_client.post("/api/shopper", json={"query": "cheap", "budget_cents": 10}).json()
    assert empty["listing_id"] is None and empty["listing"] is None
    assert seller_client.post("/api/shopper", json={"query": "q" * 1000}).status_code == 422


def test_cancel_redirect_cancels_the_purchase(seller_client, buyer_client, manager):
    listing_id = listing_for_sale(mode="hold")["id"]
    started = buyer_client.post("/api/purchases", json={"listing_id": listing_id}).json()
    cancelled = buyer_client.post("/paypal/mock-approve",
                                   data={"order": started["paypal_order_id"], "decision": "cancel"},
                                   follow_redirects=False)
    assert cancelled.headers["location"] == f"/paypal/cancel?purchase={started['purchase_id']}"
    landing = buyer_client.get(cancelled.headers["location"], follow_redirects=False)
    assert landing.headers["location"] == f"/#purchase/{started['purchase_id']}"
    assert buyer_client.get(f"/api/purchases/{started['purchase_id']}").json()["status"] == "cancelled"
    assert buyer_client.post(f"/api/purchases/{started['purchase_id']}/approve",
                              json={"order_id": started["paypal_order_id"]}).status_code == 409


def test_return_works_with_only_the_order_token(seller_client, buyer_client, manager):
    listing_id = listing_for_sale(mode="hold")["id"]
    started = buyer_client.post("/api/purchases", json={"listing_id": listing_id}).json()
    get_paypal().approve(started["paypal_order_id"])
    returned = buyer_client.get(f"/paypal/return?token={started['paypal_order_id']}", follow_redirects=False)
    assert returned.headers["location"] == f"/#purchase/{started['purchase_id']}"
    assert buyer_client.get(f"/api/purchases/{started['purchase_id']}").json()["status"] == "probation"
    assert buyer_client.get("/paypal/return?token=nope", follow_redirects=False).headers["location"] == "/#purchases"


def test_return_without_approval_keeps_the_purchase_open(seller_client, buyer_client, manager):
    for mode in ("hold", "instant"):
        listing_id = listing_for_sale(mode=mode, title=f"Agent {mode}")["id"]
        started = buyer_client.post("/api/purchases", json={"listing_id": listing_id}).json()
        returned = buyer_client.get(
            f"/paypal/return?token={started['paypal_order_id']}&purchase={started['purchase_id']}",
            follow_redirects=False)
        assert returned.status_code == 302
        assert buyer_client.get(f"/api/purchases/{started['purchase_id']}").json()["status"] == "created"


def test_mock_approve_pages_handle_unknown_orders_and_wrong_orders(client):
    assert client.get("/paypal/mock-approve?order=MOCK-ORDER-9999").status_code == 404
    assert client.post("/paypal/mock-approve", data={"order": "nope", "decision": "approve"}).status_code == 404


def test_mock_pages_are_disabled_with_real_paypal(client, monkeypatch):
    monkeypatch.setattr("parable.paypal_routes.is_mock", lambda: False)
    assert client.get("/paypal/mock-approve?order=x").status_code == 404
    assert client.post("/paypal/mock-approve", data={"order": "x"}).status_code == 404


def test_retry_endpoint_rejects_purchases_without_errors(seller_client, buyer_client, manager):
    listing_id = listing_for_sale()["id"]
    started = buyer_client.post("/api/purchases", json={"listing_id": listing_id}).json()
    assert buyer_client.post(f"/api/purchases/{started['purchase_id']}/retry").status_code == 409
    assert buyer_client.get("/api/purchases/p_missing").status_code == 404
    assert buyer_client.post("/api/purchases", json={"listing_id": "l_missing"}).status_code == 404


def test_retry_endpoint_recovers_an_errored_settlement(seller_client, buyer_client, manager, wait_until):
    listing_id = listing_for_sale(mode="hold")["id"]
    started = buy_and_approve(buyer_client, listing_id)
    get_paypal().fail_next("capture_authorization", "INTERNAL_SERVICE_ERROR")
    run_id = buyer_client.get(f"/api/purchases/{started['purchase_id']}").json()["run"]["id"]
    expire_run(run_id)
    assert wait_until(lambda: buyer_client.get(f"/api/purchases/{started['purchase_id']}").json()["status"] == "error")
    assert buyer_client.post(f"/api/purchases/{started['purchase_id']}/retry").json()["status"] == "paid_out"


def test_ledger_routes_and_tamper_demo(seller_client, manager):
    listing_for_sale()
    entries = seller_client.get("/api/ledger?kind=listing.created&limit=5").json()
    assert len(entries) == 1 and entries[0]["kind"] == "listing.created"
    older = seller_client.get(f"/api/ledger?before={entries[0]['seq']}").json()
    assert all(entry["seq"] < entries[0]["seq"] for entry in older)
    assert seller_client.get("/api/ledger?limit=100000").status_code == 200
    assert seller_client.get("/api/ledger/verify").json()["ok"] is True
    track = seller_client.get(f"/api/listings/{entries[0]['subject'].split(':')[1]}").json()["track"]
    referee.stop(track["run_id"], "loss_limit")
    tamper = seller_client.post("/api/ledger/tamper-demo").json()
    assert tamper["edited_seq"] and tamper["verify"]["ok"] is False
    assert seller_client.get("/api/ledger/verify").json()["ok"] is True


def test_webhook_router_is_mounted(client):
    sent = client.post("/paypal/webhook", json={"id": "WH-1", "event_type": "PAYMENT.CAPTURE.COMPLETED",
                                                "resource": {"id": "CAP-1"}})
    assert sent.status_code == 200 and sent.json()["verified"] is False
    assert client.get("/api/webhooks/recent").json() == []


def test_error_handlers_map_exceptions_to_short_json(manager, tmp_path):
    app = api.create_app(tmp_path)
    probe = APIRouter()

    @probe.get("/probe/paypal")
    def paypal_failure():
        raise PayPalError(422, "INSTRUMENT_DECLINED", "secret detail")

    @probe.get("/probe/referee")
    def referee_failure():
        raise RefereeError("OverTradeLimit", "too big")

    @probe.get("/probe/crash")
    def crash():
        raise RuntimeError("secret internals")

    app.include_router(probe)
    with TestClient(app, raise_server_exceptions=False) as client:
        assert client.get("/probe/paypal").json() == {"detail": "paypal: INSTRUMENT_DECLINED"}
        assert client.get("/probe/paypal").status_code == 502
        assert (client.get("/probe/referee").status_code, client.get("/probe/referee").json()) == (
            409, {"detail": "OverTradeLimit"})
        crashed = client.get("/probe/crash")
        assert crashed.status_code == 500 and crashed.json() == {"detail": "internal error"}


def test_paypal_failure_while_buying_is_a_502(seller_client, buyer_client, manager, monkeypatch):
    listing_id = listing_for_sale()["id"]

    def refuse(*args, **kwargs):
        raise PayPalError(401, "AUTHENTICATION_FAILURE", "bad credentials")

    monkeypatch.setattr(get_paypal(), "create_order", refuse)
    failed = buyer_client.post("/api/purchases", json={"listing_id": listing_id})
    assert failed.status_code == 502 and failed.json()["detail"] == "paypal: AUTHENTICATION_FAILURE"
    assert market.market_stats()["held_cents"] == 0


def test_frontend_is_served_with_no_cache_and_a_build_hint(manager, tmp_path):
    with TestClient(api.create_app(tmp_path)) as hint:
        assert "not built" in hint.get("/").text
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<html>built</html>")
    (tmp_path / "assets" / "app.js").write_text("export {}")
    with TestClient(api.create_app(tmp_path)) as built:
        home = built.get("/")
        assert home.text == "<html>built</html>" and "no-cache" in home.headers["cache-control"]
        assert built.get("/assets/app.js").status_code == 200
        assert built.get("/assets/missing.js").status_code == 404


def test_trial_listing_stats_appear_on_the_market(seller_client, buyer_client, manager):
    listing = listing_for_sale(mode="hold")
    buy_and_approve(buyer_client, listing["id"])
    stats = seller_client.get("/api/listings").json()[0]["stats"]
    assert stats["purchases"] == 1 and stats["held_cents"] == 2000
    assert referee.list_runs(purpose="probation", status="alive")
