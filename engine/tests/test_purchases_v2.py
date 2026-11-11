import json

import pytest

from market_support import approve_and_confirm, expire_run, make_listing, make_seller, purchase_row
from parable import ledger, market, referee, settlement
from parable.db import execute, rows
from parable.errors import LabError, MarketError
from parable.paypal import get_paypal

BUYER = ("Bo Buyer", "bo@example.com")


def buyer_account():
    return make_seller(*BUYER)


def start(listing, buyer=None):
    return market.start_purchase(listing["id"], (buyer or buyer_account())["id"])


def kinds(purchase_id: str) -> list[str]:
    return [entry["kind"] for entry in reversed(ledger.entries(subject=f"purchase:{purchase_id}"))]


def seq_of(kind: str, purchase_id: str) -> int:
    return next(e["seq"] for e in ledger.entries(subject=f"purchase:{purchase_id}") if e["kind"] == kind)


def test_hold_pass_captures_then_pays_out(manager, settled):
    listing = make_listing(min_return_bps=-50)
    purchase = start(listing)
    assert get_paypal().get_order(purchase["paypal_order_id"])["intent"] == "AUTHORIZE"
    row = approve_and_confirm(purchase)
    assert row["status"] == "probation" and row["mode"] == "hold" and row["buyer_id"]
    run = referee.get_run(row["run_id"])
    assert run["purpose"] == "probation" and run["version_id"] and run["seller_id"] == listing["seller_id"]
    expire_run(row["run_id"])
    done = settled(purchase["purchase_id"], ("paid_out",))
    assert done["paypal_capture_id"] and done["paypal_payout_batch_id"] and done["license_key"]
    assert json.loads(done["verdict_json"])["passed"] is True
    assert kinds(purchase["purchase_id"]) == ["purchase.created", "purchase.authorized",
                                              "purchase.probation_started", "purchase.passed", "payment.captured",
                                              "payout.sent"]


def test_hold_fail_voids_the_authorization(manager, settled):
    listing = make_listing(min_return_bps=300)
    purchase = start(listing)
    row = approve_and_confirm(purchase)
    expire_run(row["run_id"])
    done = settled(purchase["purchase_id"], ("voided",))
    verdict = json.loads(done["verdict_json"])
    assert verdict["passed"] is False and verdict["explanation"]
    assert not done["paypal_capture_id"] and not done["license_key"] and not done["paypal_payout_batch_id"]
    assert get_paypal().get_authorization(done["paypal_authorization_id"])["status"] == "VOIDED"


def test_instant_captures_before_it_pays_out(manager):
    listing = make_listing(mode="instant")
    assert listing["track_run_id"] is not None
    purchase = start(listing)
    assert get_paypal().get_order(purchase["paypal_order_id"])["intent"] == "CAPTURE"
    done = approve_and_confirm(purchase)
    assert done["status"] == "paid_out" and done["mode"] == "instant" and done["run_id"] is None
    assert done["paypal_capture_id"].startswith("MOCK-CAPTURE") and done["license_key"].startswith("pk_")
    assert seq_of("payment.captured", done["id"]) < seq_of("payout.sent", done["id"])
    assert kinds(done["id"]) == ["purchase.created", "payment.captured", "payout.sent"]


def test_instant_payout_failure_keeps_capture_and_retry_never_captures_twice(manager):
    mock = get_paypal()
    listing = make_listing(mode="instant")
    purchase = start(listing)
    mock.fail_next("create_payout", "PAYOUT_DOWN")
    row = approve_and_confirm(purchase)
    assert row["status"] == "error" and row["paypal_capture_id"] and row["license_key"]
    assert "PAYOUT_DOWN" in row["error"] and not row["paypal_payout_batch_id"]
    mock.fail_next("capture_order", "SHOULD_NEVER_BE_CALLED")
    done = market.retry_settlement(purchase["purchase_id"])
    assert done["status"] == "paid_out" and done["paypal_capture_id"] == row["paypal_capture_id"]
    assert kinds(done["id"]).count("payment.captured") == 1
    assert mock._failures["capture_order"] == ["SHOULD_NEVER_BE_CALLED"]


def test_instant_capture_failure_has_no_capture_id_and_retry_captures(manager):
    mock = get_paypal()
    purchase = start(make_listing(mode="instant"))
    mock.fail_next("capture_order", "CAPTURE_DOWN")
    row = approve_and_confirm(purchase)
    assert row["status"] == "error" and not row["paypal_capture_id"] and not row["license_key"], row["error"]
    done = market.retry_settlement(purchase["purchase_id"])
    assert done["status"] == "paid_out", done["error"]
    assert done["paypal_capture_id"]
    with pytest.raises(MarketError):
        market.retry_settlement(purchase["purchase_id"])


def test_settle_pending_finishes_an_instant_sale_after_a_restart(manager):
    purchase = start(make_listing(mode="instant"))
    get_paypal().fail_next("create_payout", "DOWN")
    approve_and_confirm(purchase)
    assert purchase_row(purchase["purchase_id"])["status"] == "error"
    assert market.settle_pending() == 1
    assert purchase_row(purchase["purchase_id"])["status"] == "paid_out"
    assert market.settle_pending() == 0


def test_self_purchase_is_refused_by_account(manager):
    seller = make_seller()
    listing = make_listing(seller)
    with pytest.raises(LabError) as problem:
        market.start_purchase(listing["id"], seller["id"])
    assert (problem.value.status, problem.value.code) == (403, "self_purchase")
    assert rows("SELECT id FROM purchases") == []


def test_self_purchase_is_refused_by_payer_id_on_hold(manager):
    seller = make_seller()
    listing = make_listing(seller)
    purchase = market.start_purchase(listing["id"], buyer_account()["id"])
    payer = rows("SELECT paypal_payer_id FROM sellers WHERE id = ?", (seller["id"],))[0]["paypal_payer_id"]
    get_paypal().approve(purchase["paypal_order_id"], payer_id=payer)
    with pytest.raises(LabError) as problem:
        market.confirm_approval(purchase["purchase_id"], purchase["paypal_order_id"])
    assert problem.value.code == "self_purchase"
    row = purchase_row(purchase["purchase_id"])
    assert row["status"] == "cancelled" and row["run_id"] is None
    assert get_paypal().get_authorization(row["paypal_authorization_id"] or "MOCK-AUTH-0001")["status"] == "VOIDED"
    assert ledger.entries(kind="purchase.cancelled")[0]["data"]["reason"] == "self_purchase"


def test_self_purchase_is_refused_by_payer_id_on_instant_before_capture(manager):
    seller = make_seller()
    listing = make_listing(seller, mode="instant")
    purchase = market.start_purchase(listing["id"], buyer_account()["id"])
    payer = rows("SELECT paypal_payer_id FROM sellers WHERE id = ?", (seller["id"],))[0]["paypal_payer_id"]
    get_paypal().approve(purchase["paypal_order_id"], payer_id=payer)
    with pytest.raises(LabError) as problem:
        market.confirm_approval(purchase["purchase_id"], purchase["paypal_order_id"])
    assert problem.value.code == "self_purchase"
    row = purchase_row(purchase["purchase_id"])
    assert row["status"] == "cancelled" and not row["paypal_capture_id"]
    assert get_paypal().get_order(purchase["paypal_order_id"])["status"] == "APPROVED"
    assert "payment.captured" not in kinds(purchase["purchase_id"])


def test_confirm_is_idempotent_and_checks_the_order(manager):
    purchase = start(make_listing(mode="instant"))
    with pytest.raises(MarketError):
        market.confirm_approval(purchase["purchase_id"], "MOCK-ORDER-9999")
    done = approve_and_confirm(purchase)
    again = market.confirm_approval(purchase["purchase_id"], purchase["paypal_order_id"])
    assert again["paypal_capture_id"] == done["paypal_capture_id"]
    assert kinds(done["id"]).count("payment.captured") == 1


def test_hold_listing_on_private_data_cannot_start_a_trial(manager):
    seller = make_seller()
    listing = make_listing(seller, symbol="sample:BTCUSDT", mode="instant")
    execute("UPDATE listings SET mode = 'hold' WHERE id = ?", (listing["id"],))
    purchase = start(listing)
    get_paypal().approve(purchase["paypal_order_id"])
    with pytest.raises(LabError) as problem:
        market.confirm_approval(purchase["purchase_id"], purchase["paypal_order_id"])
    assert (problem.value.status, problem.value.code) == (400, "bad_request")
    row = purchase_row(purchase["purchase_id"])
    assert row["status"] == "created" and not row["paypal_authorization_id"]
    execute("UPDATE purchases SET status = 'authorized' WHERE id = ?", (row["id"],))
    from parable.purchases import begin_probation

    begin_probation(purchase_row(row["id"]))
    stuck = purchase_row(row["id"])
    assert stuck["status"] == "error" and "live market data" in stuck["error"] and stuck["run_id"] is None
    assert rows("SELECT id FROM runs WHERE purpose = 'probation'") == []


def test_cancel_unapproved_purchases(manager):
    purchase = start(make_listing(mode="instant"))
    execute("UPDATE purchases SET created_at = 1 WHERE id = ?", (purchase["purchase_id"],))
    assert market.cancel_unapproved() == 1
    assert purchase_row(purchase["purchase_id"])["status"] == "cancelled"


def test_paused_listing_cannot_be_bought(manager):
    seller = make_seller()
    listing = make_listing(seller)
    market.pause_listing(seller["id"], listing["id"])
    with pytest.raises(MarketError):
        start(listing)


def test_settlement_helpers_keep_working_for_live_statuses(manager):
    purchase = start(make_listing())
    row = approve_and_confirm(purchase)
    assert row["status"] == "probation"
    assert settlement.settle_pending() == 0


def flow_account(email: str) -> dict:
    return rows("SELECT * FROM sellers WHERE email = ?", (email,))[0]


def bought_instant(seller_client, buyer_client, **listing_options):
    from api_support import buy_and_approve

    seller = flow_account("flow@example.com")
    listing = make_listing(seller, mode="instant", **listing_options)
    started = buy_and_approve(buyer_client, listing["id"])
    return listing, started


def test_purchase_routes_require_sign_in(client):
    for method, path in (("post", "/api/purchases"), ("get", "/api/purchases/p_x"), ("get", "/api/me/agents"),
                         ("get", "/api/me/purchases"), ("get", "/api/me/sales"),
                         ("get", "/api/purchases/p_x/license"), ("post", "/api/purchases/p_x/run")):
        response = getattr(client, method)(path)
        assert response.status_code == 401 and response.json()["code"] == "unauthorized"


def test_http_instant_flow_license_download_and_run(seller_client, buyer_client, manager):
    listing, started = bought_instant(seller_client, buyer_client)
    view = buyer_client.get(f"/api/purchases/{started['purchase_id']}").json()
    assert view["status"] == "paid_out" and view["mode"] == "instant" and view["run"] is None
    assert view["paypal_capture_id"].startswith("***") and view["payout_cents"] == 1800
    assert view["license"]["format"] == "parable-agent" and view["license"]["spec"]["entry"]
    assert view["license"]["steps_text"] == "buy dips, sell rips" and view["license"]["proof_id"]
    assert view["listing"]["id"] == listing["id"] and "spec" not in view["listing"]
    download = buyer_client.get(f"/api/purchases/{started['purchase_id']}/license")
    assert download.status_code == 200
    disposition = download.headers["content-disposition"]
    assert disposition.startswith('attachment; filename="test-agent-') and disposition.endswith('.json"')
    assert disposition.split("-")[-1][:8] == view["license"]["spec_hash"][:8]
    assert download.json() == view["license"]
    ran = buyer_client.post(f"/api/purchases/{started['purchase_id']}/run", json={"start_cash": 500})
    assert ran.status_code == 200
    run = ran.json()
    assert run["purpose"] == "practice" and run["start_cash_usd"] == 500 * 1_000_000
    assert run["seller_id"] == flow_account("buyer@example.com")["id"] and run["status"] == "alive"
    assert "version_id" not in run and "rules" not in run


def test_only_the_buyer_sees_a_purchase(seller_client, buyer_client, manager):
    _, started = bought_instant(seller_client, buyer_client)
    pid = started["purchase_id"]
    for path in (f"/api/purchases/{pid}", f"/api/purchases/{pid}/license"):
        assert seller_client.get(path).status_code == 404
    assert seller_client.post(f"/api/purchases/{pid}/run").status_code == 404
    assert seller_client.post(f"/api/purchases/{pid}/retry").status_code == 404
    assert seller_client.post(f"/api/purchases/{pid}/approve", json={"order_id": started["paypal_order_id"]}
                              ).status_code == 404


def test_license_and_run_need_a_paid_purchase(seller_client, buyer_client, manager):
    seller = flow_account("flow@example.com")
    listing = make_listing(seller, mode="instant")
    started = buyer_client.post("/api/purchases", json={"listing_id": listing["id"]}).json()
    pid = started["purchase_id"]
    assert buyer_client.get(f"/api/purchases/{pid}").json()["license"] is None
    for method, path in (("get", f"/api/purchases/{pid}/license"), ("post", f"/api/purchases/{pid}/run")):
        response = getattr(buyer_client, method)(path)
        assert response.status_code == 403 and response.json()["code"] == "not_entitled"


def test_run_on_parable_refuses_private_data(seller_client, buyer_client, manager):
    seller = flow_account("flow@example.com")
    listing = make_listing(seller, mode="instant", symbol="sample:BTCUSDT", title="Sample Agent")
    assert listing["track_run_id"] is None
    from api_support import buy_and_approve

    started = buy_and_approve(buyer_client, listing["id"])
    response = buyer_client.post(f"/api/purchases/{started['purchase_id']}/run")
    assert response.status_code == 400 and response.json()["code"] == "bad_request"


def test_self_purchase_over_http(seller_client, manager):
    listing = make_listing(flow_account("flow@example.com"))
    response = seller_client.post("/api/purchases", json={"listing_id": listing["id"]})
    assert response.status_code == 403 and response.json()["code"] == "self_purchase"


def test_purchase_view_never_carries_spec_text(seller_client, buyer_client, manager):
    listing, started = bought_instant(seller_client, buyer_client)
    view = buyer_client.get(f"/api/purchases/{started['purchase_id']}").json()
    without_license = json.dumps({**view, "license": None})
    from parable.lab.templates import template_spec

    assert template_spec("trend", "x", "1h").entry not in without_license


def test_me_endpoints(seller_client, buyer_client, manager):
    listing, started = bought_instant(seller_client, buyer_client)
    sales = seller_client.get("/api/me/sales").json()
    assert sales == [{"listing_id": listing["id"], "title": "Test Agent", "mode": "instant", "purchases": 1,
                      "captured_cents": 2000, "paid_out_cents": 1800}]
    assert buyer_client.get("/api/me/sales").json() == []
    purchases = buyer_client.get("/api/me/purchases").json()
    assert purchases[0]["id"] == started["purchase_id"] and purchases[0]["title"] == "Test Agent"
    mine = buyer_client.get("/api/me/agents").json()
    assert mine["built"] == [] and mine["bought"][0]["entitled"] is True and mine["bought"][0]["spec_hash"]
    built = seller_client.get("/api/me/agents").json()["built"][0]
    assert built["status"] == "listed" and built["listing_id"] == listing["id"] and built["headline"]["trades"] >= 0
    assert seller_client.get("/api/me").json()["free_tries"]["limit"] == 5


def test_approve_over_http_returns_the_purchase_view(seller_client, buyer_client, manager):
    from api_support import approve_in_paypal

    listing = make_listing(flow_account("flow@example.com"), mode="instant")
    started = buyer_client.post("/api/purchases", json={"listing_id": listing["id"]}).json()
    approve_in_paypal(buyer_client, started)
    done = buyer_client.post(f"/api/purchases/{started['purchase_id']}/approve",
                             json={"order_id": started["paypal_order_id"]})
    assert done.status_code == 200 and done.json()["status"] == "paid_out"


def test_created_purchase_exposes_the_paypal_link_until_approval(manager):
    from parable.purchase_views import get_purchase

    buyer = buyer_account()
    purchase = market.start_purchase(make_listing()["id"], buyer["id"])
    view = get_purchase(purchase["purchase_id"], buyer["id"])
    assert view["status"] == "created" and view["approve_url"] == purchase["approve_url"]
    row = approve_and_confirm(purchase)
    assert row["status"] != "created"
    assert get_purchase(purchase["purchase_id"], buyer["id"])["approve_url"] == ""
