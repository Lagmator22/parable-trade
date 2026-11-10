from fastapi.testclient import TestClient

from api_support import LISTING_BODY, approve_in_paypal, buy_and_approve, order_from
from market_support import expire_run, install_manager
from parable import api, ledger, referee, runs


def paid_status(client, purchase_id: str, wait_until, statuses) -> dict:
    assert wait_until(lambda: client.get(f"/api/purchases/{purchase_id}").json()["status"] in statuses)
    return client.get(f"/api/purchases/{purchase_id}").json()


def test_unauthenticated_listing_create_is_401(client):
    response = client.post("/api/listings", json=LISTING_BODY)
    assert response.status_code == 401 and response.json() == {"detail": "sign in with PayPal first"}
    assert client.get("/api/me").json()["seller"] is None


def test_full_flow_pass_pays_the_seller_and_issues_a_license(seller_client, manager, price_box, wait_until):
    me = seller_client.get("/api/me").json()
    assert me["paypal_mode"] == "mock" and me["seller"]["name"] == "Flow Seller"
    listing = seller_client.post("/api/listings", json=LISTING_BODY).json()
    assert listing["seller"]["id"] == me["seller"]["id"]

    started = seller_client.post("/api/purchases", json={"listing_id": listing["id"]}).json()
    assert order_from(started["approve_url"]) == started["paypal_order_id"]
    page = seller_client.get(started["approve_url"].replace("http://localhost:8000", ""))
    assert page.status_code == 200 and "Mock PayPal" in page.text and "$20.00" in page.text
    assert seller_client.get(f"/api/purchases/{started['purchase_id']}").json()["status"] == "created"

    landing = approve_in_paypal(seller_client, started)
    assert landing == f"/paypal/return?token={started['paypal_order_id']}&purchase={started['purchase_id']}"
    returned = seller_client.get(landing, follow_redirects=False)
    assert returned.status_code == 302 and returned.headers["location"] == f"/#purchase/{started['purchase_id']}"

    live = seller_client.get(f"/api/purchases/{started['purchase_id']}").json()
    assert live["status"] == "probation" and live["run"]["purpose"] == "probation"
    approved_again = [
        seller_client.post(f"/api/purchases/{started['purchase_id']}/approve",
                           json={"order_id": started["paypal_order_id"]}).json()
        for _ in range(2)
    ]
    assert {item["run"]["id"] for item in approved_again} == {live["run"]["id"]}
    assert len(ledger.entries(kind="purchase.probation_started")) == 1

    stop = seller_client.post(f"/api/runs/{live['run']['id']}/stop")
    assert stop.status_code == 403 and "probation" in stop.json()["detail"]
    assert referee.get_run(live["run"]["id"])["status"] == "alive"

    assert expire_run(live["run"]["id"])["cause"] == "expired"
    manager.poll_once()
    done = paid_status(seller_client, started["purchase_id"], wait_until, ("paid_out", "error"))
    assert done["status"] == "paid_out" and done["verdict"]["passed"] is True
    assert done["payout_status"] == "SUCCESS" and done["paypal_capture_id"].startswith("***")

    token = {"x-buyer-token": started["buyer_token"]}
    owner_view = seller_client.get(f"/api/purchases/{started['purchase_id']}", headers=token).json()
    assert owner_view["license"]["key"].startswith("pk_")
    for headers in ({}, {"x-buyer-token": "wrong-token"}):
        assert seller_client.get(f"/api/purchases/{started['purchase_id']}", headers=headers).json()["license"] is None

    assert seller_client.get("/api/ledger/verify").json()["ok"] is True
    stats = seller_client.get("/api/stats").json()
    assert stats["passed"] == 1 and stats["paid_out_cents"] == 1800 and stats["held_cents"] == 0


def test_full_flow_loss_voids_and_charges_nothing(seller_client, manager, price_box, wait_until):
    listing = seller_client.post("/api/listings", json={**LISTING_BODY, "title": "Doomed Bot"}).json()
    started = buy_and_approve(seller_client, listing["id"])
    live = seller_client.get(f"/api/purchases/{started['purchase_id']}").json()
    assert live["status"] == "probation"
    assert wait_until(lambda: referee.get_run(live["run"]["id"])["trades"] >= 1)
    price_box.set(1500)
    ended = manager.poll_once()
    assert [run["cause"] for run in ended] == ["loss_limit"]
    done = paid_status(seller_client, started["purchase_id"], wait_until, ("voided", "error"))
    assert done["status"] == "voided" and done["verdict"]["cause"] == "loss_limit"
    assert done["paypal_capture_id"] == "" and done["paypal_payout_batch_id"] == ""
    owner_view = seller_client.get(f"/api/purchases/{started['purchase_id']}",
                                   headers={"x-buyer-token": started["buyer_token"]}).json()
    assert owner_view["license"] is None
    assert seller_client.get("/api/ledger/verify").json()["ok"] is True
    stats = seller_client.get("/api/stats").json()
    assert stats["failed"] == 1 and stats["voided_cents"] == 2000 and stats["captured_cents"] == 0
    record = seller_client.get(f"/api/sellers/{listing['seller']['id']}").json()["record"]
    assert record["probation_failed"] == 1 and record["loss_limit"] == 1


def test_lifespan_starts_and_stops_background_services(manager, tmp_path):
    with TestClient(api.create_app(tmp_path)):
        assert manager.poller is not None and manager.poller.is_alive()
        assert manager.dispatch_end in referee._end_hooks
    assert not manager.poller.is_alive()


def test_boot_settles_probations_that_ended_while_the_server_was_down(seller_client, manager, price_box, tmp_path,
                                                                     wait_until):
    listing = seller_client.post("/api/listings", json=LISTING_BODY).json()
    started = buy_and_approve(seller_client, listing["id"])
    run_id = seller_client.get(f"/api/purchases/{started['purchase_id']}").json()["run"]["id"]
    referee.clear_end_hooks()
    expire_run(run_id)
    assert seller_client.get(f"/api/purchases/{started['purchase_id']}").json()["status"] == "probation"
    runs.set_manager(None)
    install_manager()
    with TestClient(api.create_app(tmp_path)) as rebooted:
        done = paid_status(rebooted, started["purchase_id"], wait_until, ("paid_out", "error"))
    assert done["status"] == "paid_out"
