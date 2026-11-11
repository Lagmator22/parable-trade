from fastapi.testclient import TestClient

from api_support import buy_and_approve
from market_support import expire_run, install_manager, make_listing
from parable import api, referee, runs
from parable.db import one


def paid_status(client, purchase_id: str, wait_until, statuses) -> dict:
    assert wait_until(lambda: client.get(f"/api/purchases/{purchase_id}").json()["status"] in statuses)
    return client.get(f"/api/purchases/{purchase_id}").json()


def flow_seller() -> dict:
    return one("SELECT id FROM sellers WHERE email = ?", ("flow@example.com",))


def test_hold_pass_pays_the_seller_and_issues_a_license(seller_client, buyer_client, manager, wait_until):
    listing = make_listing(flow_seller(), min_return_bps=0)
    started = buy_and_approve(buyer_client, listing["id"])
    live = buyer_client.get(f"/api/purchases/{started['purchase_id']}").json()
    assert live["status"] == "probation" and live["license"] is None and live["run"]["purpose"] == "probation"
    expire_run(live["run"]["id"])
    done = paid_status(buyer_client, started["purchase_id"], wait_until, ("paid_out", "error"))
    assert done["status"] == "paid_out" and done["verdict"]["passed"] is True
    assert done["license"]["key"].startswith("pk_") and done["license"]["spec"]["symbol"] == "fake:BTCUSDT"
    assert done["fee_cents"] == 200 and done["payout_cents"] == 1800
    record = seller_client.get(f"/api/sellers/{listing['seller_id']}").json()["record"]
    assert record["probation_passed"] == 1 and record["track_runs"] == 1


def test_hold_fail_voids_and_charges_nothing(seller_client, buyer_client, manager, wait_until):
    listing = make_listing(flow_seller(), min_return_bps=400)
    started = buy_and_approve(buyer_client, listing["id"])
    run_id = buyer_client.get(f"/api/purchases/{started['purchase_id']}").json()["run"]["id"]
    expire_run(run_id)
    done = paid_status(buyer_client, started["purchase_id"], wait_until, ("voided", "error"))
    assert done["status"] == "voided" and done["verdict"]["passed"] is False and done["license"] is None
    assert done["paypal_capture_id"] == "" and done["verdict"]["explanation"]
    record = seller_client.get(f"/api/sellers/{listing['seller_id']}").json()["record"]
    assert record["probation_failed"] == 1


def test_lifespan_starts_and_stops_background_services(manager, tmp_path):
    with TestClient(api.create_app(tmp_path)):
        assert manager.poller is not None and manager.poller.is_alive()
        assert manager.dispatch_end in referee._end_hooks
    assert not manager.poller.is_alive()


def test_boot_settles_probations_that_ended_while_the_server_was_down(seller_client, buyer_client, manager, tmp_path,
                                                                     wait_until):
    listing = make_listing(flow_seller())
    started = buy_and_approve(buyer_client, listing["id"])
    run_id = buyer_client.get(f"/api/purchases/{started['purchase_id']}").json()["run"]["id"]
    referee.clear_end_hooks()
    expire_run(run_id)
    assert buyer_client.get(f"/api/purchases/{started['purchase_id']}").json()["status"] == "probation"
    runs.set_manager(None)
    install_manager()
    with TestClient(api.create_app(tmp_path)) as rebooted:
        rebooted.cookies.update(buyer_client.cookies)
        done = paid_status(rebooted, started["purchase_id"], wait_until, ("paid_out", "error"))
    assert done["status"] == "paid_out"


def test_boot_restarts_missing_tracks_and_finishes_instant_sales(seller_client, buyer_client, manager, tmp_path):
    from parable.paypal import get_paypal

    listing = make_listing(flow_seller(), mode="instant")
    get_paypal().fail_next("create_payout", "DOWN")
    started = buy_and_approve(buyer_client, listing["id"])
    assert buyer_client.get(f"/api/purchases/{started['purchase_id']}").json()["status"] == "error"
    referee.stop(listing["track_run_id"], "stopped")
    runs.set_manager(None)
    install_manager()
    with TestClient(api.create_app(tmp_path)) as rebooted:
        rebooted.cookies.update(buyer_client.cookies)
        assert rebooted.get(f"/api/purchases/{started['purchase_id']}").json()["status"] == "paid_out"
        track = rebooted.get(f"/api/listings/{listing['id']}").json()["track"]
        assert track["status"] == "alive" and track["runs_total"] == 2


def test_favicon_request_is_quiet(client):
    assert client.get("/favicon.ico").status_code == 204
