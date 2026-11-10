from fastapi import APIRouter
from fastapi.testclient import TestClient

from api_support import LISTING_BODY, buy_and_approve
from market_support import expire_run
from parable import api, market, referee
from parable.paypal import PayPalError, get_paypal
from parable.referee import RefereeError


def test_info_describes_the_deployment(client):
    info = client.get("/api/info").json()
    assert info["paypal_mode"] == "mock" and info["paypal_client_id"] == "" and info["currency"] == "USD"
    assert info["platform_fee_bps"] == 1000 and info["eth_price_usd"] > 0 and info["analyst"] == "rules"
    assert {"id": "yolo", "text": info["strategies"][-1]["text"]} in info["strategies"]
    assert {"brain": "rule", "available": True} in info["brains"]
    assert info["ledger_head"]["seq"] >= 0


def test_prices_always_return_a_point(client):
    points = client.get("/api/prices").json()["points"]
    assert points and isinstance(points[0][1], float)


def test_listing_routes_and_validation(seller_client):
    created = seller_client.post("/api/listings", json=LISTING_BODY)
    assert created.status_code == 200
    listing_id = created.json()["id"]
    assert [item["id"] for item in seller_client.get("/api/listings").json()] == [listing_id]
    detail = seller_client.get(f"/api/listings/{listing_id}").json()
    assert detail["id"] == listing_id and detail["runs"] == []
    invalid = seller_client.post("/api/listings", json={**LISTING_BODY, "price_cents": 5})
    assert invalid.status_code == 422 and invalid.json()["detail"].startswith("price_cents")
    assert seller_client.post("/api/listings", json={**LISTING_BODY, "strategy": "tea"}).status_code == 400
    assert seller_client.get("/api/listings/l_unknown").status_code == 404
    paused = seller_client.post(f"/api/listings/{listing_id}/pause").json()
    assert paused["active"] is False and seller_client.get("/api/listings").json() == []


def test_only_the_owner_can_pause_or_practice(seller_client):
    listing_id = seller_client.post("/api/listings", json=LISTING_BODY).json()["id"]
    seller_client.post("/api/logout")
    stranger = TestClient(seller_client.app)
    stranger.post("/paypal/mock-login", data={"name": "Other", "email": "other@example.com"}, follow_redirects=False)
    assert stranger.post(f"/api/listings/{listing_id}/pause").status_code == 403
    assert stranger.post(f"/api/listings/{listing_id}/practice").status_code == 403
    assert seller_client.post(f"/api/listings/{listing_id}/practice").status_code == 401


def test_practice_run_can_be_stopped_by_its_owner(seller_client):
    listing_id = seller_client.post("/api/listings", json=LISTING_BODY).json()["id"]
    run = seller_client.post(f"/api/listings/{listing_id}/practice").json()
    assert run["purpose"] == "practice" and "rules_json" not in run
    stopped = seller_client.post(f"/api/runs/{run['id']}/stop").json()
    assert stopped["status"] == "dead" and stopped["cause"] == "stopped"
    detail = seller_client.get(f"/api/runs/{run['id']}").json()
    assert detail["id"] == run["id"] and any(entry["kind"] == "run.ended" for entry in detail["entries"])
    listed = seller_client.get(f"/api/runs?seller={run['seller_id']}&status=dead&purpose=practice").json()
    assert [item["id"] for item in listed] == [run["id"]]
    assert seller_client.get("/api/runs/9999").status_code == 404
    assert seller_client.get(f"/api/listings/{listing_id}").json()["runs"][0]["id"] == run["id"]


def test_seller_profile(seller_client):
    seller = seller_client.get("/api/me").json()["seller"]
    seller_client.post("/api/listings", json=LISTING_BODY)
    profile = seller_client.get(f"/api/sellers/{seller['id']}").json()
    assert profile["seller"]["name"] == "Flow Seller" and profile["record"]["runs"] == 0
    assert len(profile["listings"]) == 1
    assert seller_client.get("/api/sellers/s_missing").status_code == 404


def test_diligence_and_shopper_endpoints(seller_client):
    listing = seller_client.post("/api/listings", json=LISTING_BODY).json()
    report = seller_client.get(f"/api/listings/{listing['id']}/diligence").json()
    assert report["risk"] in ("low", "medium", "high") and report["by"] == "rules"
    answer = seller_client.post("/api/shopper", json={"query": "a cheap bot", "budget_cents": 5000}).json()
    assert answer["listing_id"] == listing["id"] and answer["listing"]["id"] == listing["id"]
    empty = seller_client.post("/api/shopper", json={"query": "cheap", "budget_cents": 10}).json()
    assert empty["listing_id"] is None and empty["listing"] is None
    assert seller_client.post("/api/shopper", json={"query": "q" * 1000}).status_code == 422


def test_cancel_redirect_cancels_the_purchase(seller_client):
    listing_id = seller_client.post("/api/listings", json=LISTING_BODY).json()["id"]
    started = seller_client.post("/api/purchases", json={"listing_id": listing_id}).json()
    cancelled = seller_client.post("/paypal/mock-approve",
                                   data={"order": started["paypal_order_id"], "decision": "cancel"},
                                   follow_redirects=False)
    assert cancelled.headers["location"] == f"/paypal/cancel?purchase={started['purchase_id']}"
    landing = seller_client.get(cancelled.headers["location"], follow_redirects=False)
    assert landing.headers["location"] == f"/#purchase/{started['purchase_id']}"
    assert seller_client.get(f"/api/purchases/{started['purchase_id']}").json()["status"] == "cancelled"
    assert seller_client.post(f"/api/purchases/{started['purchase_id']}/approve",
                              json={"order_id": started["paypal_order_id"]}).status_code == 409


def test_return_works_with_only_the_order_token(seller_client):
    listing_id = seller_client.post("/api/listings", json=LISTING_BODY).json()["id"]
    started = seller_client.post("/api/purchases", json={"listing_id": listing_id}).json()
    get_paypal().approve(started["paypal_order_id"])
    returned = seller_client.get(f"/paypal/return?token={started['paypal_order_id']}", follow_redirects=False)
    assert returned.headers["location"] == f"/#purchase/{started['purchase_id']}"
    assert seller_client.get(f"/api/purchases/{started['purchase_id']}").json()["status"] == "probation"
    assert seller_client.get("/paypal/return?token=nope", follow_redirects=False).headers["location"] == "/#purchases"


def test_return_without_approval_keeps_the_purchase_open(seller_client):
    listing_id = seller_client.post("/api/listings", json=LISTING_BODY).json()["id"]
    started = seller_client.post("/api/purchases", json={"listing_id": listing_id}).json()
    returned = seller_client.get(f"/paypal/return?token={started['paypal_order_id']}&purchase={started['purchase_id']}",
                                 follow_redirects=False)
    assert returned.status_code == 302
    assert seller_client.get(f"/api/purchases/{started['purchase_id']}").json()["status"] == "created"


def test_mock_approve_pages_handle_unknown_orders_and_wrong_orders(client):
    assert client.get("/paypal/mock-approve?order=MOCK-ORDER-9999").status_code == 404
    assert client.post("/paypal/mock-approve", data={"order": "nope", "decision": "approve"}).status_code == 404


def test_mock_pages_are_disabled_with_real_paypal(client, monkeypatch):
    monkeypatch.setattr("parable.paypal_routes.is_mock", lambda: False)
    assert client.get("/paypal/mock-approve?order=x").status_code == 404
    assert client.post("/paypal/mock-approve", data={"order": "x"}).status_code == 404


def test_retry_endpoint_rejects_purchases_without_errors(seller_client):
    listing_id = seller_client.post("/api/listings", json=LISTING_BODY).json()["id"]
    started = seller_client.post("/api/purchases", json={"listing_id": listing_id}).json()
    assert seller_client.post(f"/api/purchases/{started['purchase_id']}/retry").status_code == 409
    assert seller_client.get("/api/purchases/p_missing").status_code == 404
    assert seller_client.post("/api/purchases", json={"listing_id": "l_missing"}).status_code == 404


def test_retry_endpoint_recovers_an_errored_settlement(seller_client, manager, price_box, wait_until, monkeypatch):
    listing_id = seller_client.post("/api/listings", json=LISTING_BODY).json()["id"]
    started = buy_and_approve(seller_client, listing_id)
    paypal = get_paypal()
    real = paypal.capture_authorization

    def broken(*args, **kwargs):
        raise PayPalError(500, "INTERNAL_SERVICE_ERROR", "down")

    monkeypatch.setattr(paypal, "capture_authorization", broken)
    run_id = seller_client.get(f"/api/purchases/{started['purchase_id']}").json()["run"]["id"]
    expire_run(run_id)
    assert wait_until(lambda: seller_client.get(f"/api/purchases/{started['purchase_id']}").json()["status"] == "error")
    monkeypatch.setattr(paypal, "capture_authorization", real)
    assert seller_client.post(f"/api/purchases/{started['purchase_id']}/retry").json()["status"] == "paid_out"


def test_ledger_routes_and_tamper_demo(seller_client):
    seller_client.post("/api/listings", json=LISTING_BODY)
    entries = seller_client.get("/api/ledger?kind=listing.created&limit=5").json()
    assert len(entries) == 1 and entries[0]["kind"] == "listing.created"
    older = seller_client.get(f"/api/ledger?before={entries[0]['seq']}").json()
    assert all(entry["seq"] < entries[0]["seq"] for entry in older)
    assert seller_client.get("/api/ledger?limit=100000").status_code == 200
    assert seller_client.get("/api/ledger/verify").json()["ok"] is True
    run = seller_client.post(f"/api/listings/{entries[0]['subject'].split(':')[1]}/practice").json()
    seller_client.post(f"/api/runs/{run['id']}/stop")
    tamper = seller_client.post("/api/ledger/tamper-demo").json()
    assert tamper["edited_seq"] and tamper["verify"]["ok"] is False
    assert seller_client.get("/api/ledger/verify").json()["ok"] is True


def test_webhook_router_is_mounted(client):
    sent = client.post("/paypal/webhook", json={"id": "WH-1", "event_type": "PAYMENT.CAPTURE.COMPLETED",
                                                "resource": {"id": "CAP-1"}})
    assert sent.status_code == 200 and sent.json()["verified"] is False
    assert client.get("/api/webhooks/recent").json()[0]["resource_id"] == "CAP-1"


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


def test_paypal_failure_while_buying_is_a_502(seller_client, monkeypatch):
    listing_id = seller_client.post("/api/listings", json=LISTING_BODY).json()["id"]

    def refuse(*args, **kwargs):
        raise PayPalError(401, "AUTHENTICATION_FAILURE", "bad credentials")

    monkeypatch.setattr(get_paypal(), "create_order", refuse)
    failed = seller_client.post("/api/purchases", json={"listing_id": listing_id})
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


def test_probation_listing_stats_appear_on_the_market(seller_client, manager, price_box):
    listing = seller_client.post("/api/listings", json=LISTING_BODY).json()
    buy_and_approve(seller_client, listing["id"])
    stats = seller_client.get("/api/listings").json()[0]["stats"]
    assert stats["purchases"] == 1 and stats["held_cents"] == 2000
    assert referee.list_runs(purpose="probation", status="alive")
