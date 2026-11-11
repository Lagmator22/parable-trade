import json

import pytest

from market_support import fake_provider, make_listing, make_proof, make_seller
from parable import ledger, listings, market, referee
from parable.db import execute, one, rows
from parable.errors import LabError
from parable.lab.templates import template_spec
from parable.models import NewListing


def new_listing_for(owner, version_id, proof_id, **overrides):
    base = {"version_id": version_id, "title": "Second Agent", "pitch": "x", "price_cents": 1500, "mode": "hold",
            "trial_s": 120, "min_return_bps": 0, "max_loss_bps": 500, "proof_id": proof_id}
    return market.create_listing(owner["id"], NewListing(**{**base, **overrides}))


def flow_seller():
    return one("SELECT id FROM sellers WHERE email = ?", ("flow@example.com",))


def dump(value) -> str:
    return json.dumps(value)


def entry_formula(listing) -> str:
    return template_spec("trend", "fake:BTCUSDT", "1h").entry


def test_create_listing_copies_proof_and_starts_a_track(manager):
    seller = make_seller()
    listing = make_listing(seller)
    assert listing["symbol"] == "fake:BTCUSDT" and listing["interval"] == "1h"
    assert listing["trial_s"] == listing["probation_s"] == 120
    assert one("SELECT status FROM agents WHERE owner_id = ?", (seller["id"],))["status"] == "listed"
    track = referee.get_run(listing["track_run_id"])
    assert track["purpose"] == "track" and track["listing_id"] == listing["id"] and track["seller_id"] == seller["id"]
    created = ledger.entries(kind="listing.created")[0]["data"]
    assert created["version_id"] == listing["version_id"] and created["mode"] == "hold"
    assert set(created) >= {"spec_hash", "result_hash", "proof_id", "price_cents", "trial_s", "max_loss_bps"}


def test_public_view_is_an_allow_list_without_the_spec(manager):
    listing = make_listing()
    view = market.listing_detail(listing["id"])
    text = dump(view)
    assert entry_formula(listing) not in text and listing["version_id"] not in text
    assert "steps_text" not in text and "buy dips" not in text
    assert set(view["headline"]) == {"total_return_pct", "benchmark_return_pct", "max_drawdown_pct", "sharpe",
                                     "win_rate_pct", "trades"}
    assert view["kind"] == "crypto" and view["data"]["symbol"] == "fake:BTCUSDT" and len(view["sparkline"]) <= 60
    assert view["proof"]["id"] == view["proof_id"] and "trades" not in view["proof"]
    assert view["track"]["quote"] == "USDT" and view["track"]["runs_total"] == 1
    assert view["reruns"] == {"count": 0, "matched": 0} and view["built_by"] == "template:trend"
    assert view["recent_runs"][0]["purpose"] == "track" and "rules" not in view["recent_runs"][0]


def test_proof_must_be_a_backtest_of_that_exact_version(manager):
    seller = make_seller()
    first = make_listing(seller)
    other_version, other_proof = make_proof(seller, "fake:ETHUSDT", "1h", "rsi", "Other")
    with pytest.raises(LabError) as problem:
        new_listing_for(seller, first["version_id"], other_proof["id"])
    assert (problem.value.status, problem.value.code) == (400, "bad_request")
    with pytest.raises(LabError):
        new_listing_for(seller, first["version_id"], "pf_missing")
    assert new_listing_for(seller, other_version["id"], other_proof["id"])["symbol"] == "fake:ETHUSDT"


def test_only_the_owner_may_list_a_version(manager):
    owner, stranger = make_seller(), make_seller("Eve", "eve@example.com")
    version, proof = make_proof(owner, "fake:BTCUSDT", "1h")
    with pytest.raises(LabError) as problem:
        new_listing_for(stranger, version["id"], proof["id"])
    assert problem.value.status == 403
    with pytest.raises(LabError) as missing:
        new_listing_for(owner, "v_nope", proof["id"])
    assert missing.value.status == 404


def test_hold_mode_is_refused_for_sample_and_has_no_track(manager):
    seller = make_seller()
    version, proof = make_proof(seller, "sample:BTCUSDT", "1h")
    with pytest.raises(LabError) as problem:
        new_listing_for(seller, version["id"], proof["id"], mode="hold")
    assert (problem.value.status, problem.value.code) == (400, "bad_request")
    assert "instant" in problem.value.detail
    listing = new_listing_for(seller, version["id"], proof["id"], mode="instant")
    assert listing["track_run_id"] is None
    assert rows("SELECT id FROM runs WHERE purpose = 'track'") == []
    assert market.listing_detail(listing["id"])["track"] is None
    assert listings.ensure_tracks() == 0
    assert market.listing_detail(listing["id"])["data"]["source_kind"] == "sample"


def test_pause_stops_the_track_and_resume_starts_a_new_one(manager):
    seller = make_seller()
    listing = make_listing(seller)
    market.pause_listing(seller["id"], listing["id"])
    assert referee.get_run(listing["track_run_id"])["status"] == "dead"
    assert market.list_listings() == []
    market.resume_listing(seller["id"], listing["id"])
    fresh = listings.listing_row(listing["id"])
    assert fresh["active"] == 1 and fresh["track_run_id"] != listing["track_run_id"]
    assert referee.get_run(fresh["track_run_id"])["status"] == "alive"
    track = market.listing_summary(listing["id"])["track"]
    assert track["runs_total"] == 2 and track["runs_ended_early"] == 0


def test_ensure_tracks_restarts_dead_tracks_and_counts_deaths(manager):
    listing = make_listing()
    referee.stop(listing["track_run_id"], "loss_limit")
    execute("UPDATE runs SET cause = 'loss_limit' WHERE id = ?", (listing["track_run_id"],))
    assert listings.ensure_tracks() == 1
    assert listings.ensure_tracks() == 0
    track = market.listing_summary(listing["id"])["track"]
    assert track["runs_total"] == 2 and track["runs_ended_early"] == 1 and track["status"] == "alive"


def test_poll_hook_runs_at_most_once_a_minute(manager, monkeypatch):
    listing = make_listing()
    referee.stop(listing["track_run_id"], "stopped")
    manager.poll_once()
    assert len(rows("SELECT id FROM runs WHERE purpose = 'track'")) == 2
    referee.stop(listings.listing_row(listing["id"])["track_run_id"], "stopped")
    manager.poll_once()
    assert len(rows("SELECT id FROM runs WHERE purpose = 'track'")) == 2
    listings.reset_throttle()
    manager.poll_once()
    assert len(rows("SELECT id FROM runs WHERE purpose = 'track'")) == 3


def test_reruns_are_counted_publicly(manager):
    from parable import proofs

    listing = make_listing()
    assert proofs.rerun_listing(listing["id"], "v_abcdef0123456789")["match"] is True
    view = market.listing_summary(listing["id"])
    assert view["reruns"] == {"count": 1, "matched": 1}
    detail = market.listing_detail(listing["id"])
    assert len(detail["proofs"]) == 1 and detail["proofs"][0]["kind"] == "rerun"


def test_list_filters_and_sorting(manager):
    seller = make_seller()
    make_listing(seller, title="Cheap Hold", price_cents=1000)
    sample_version, sample_proof = make_proof(seller, "sample:BTCUSDT", "1h", "rsi", "Sample Agent")
    new_listing_for(seller, sample_version["id"], sample_proof["id"], mode="instant", price_cents=3000)
    assert {item["title"] for item in market.list_listings(mode="instant")} == {"Second Agent"}
    assert [item["title"] for item in market.list_listings(sort="price")] == ["Cheap Hold", "Second Agent"]
    assert [item["kind"] for item in market.list_listings(kind="crypto")] == ["crypto", "crypto"]
    assert market.list_listings(kind="stocks") == []
    by_return = market.list_listings(sort="return")
    returns = [item["headline"]["total_return_pct"] for item in by_return]
    assert returns == sorted(returns, reverse=True)


def test_attach_benchmark_checks_owner_and_agent(manager):
    seller = make_seller()
    listing = make_listing(seller)
    agent_id = one("SELECT agent_id FROM agent_versions WHERE id = ?", (listing["version_id"],))["agent_id"]
    result = {"id": "bm_1", "agent_id": agent_id, "data": {"symbol": "fake:BTCUSDT"},
              "buy_and_hold": {"metrics": {"total_return_pct": 1, "max_drawdown_pct": 2}, "curve": [[1, 2]]},
              "rows": [{"model": "gemini:x", "ok": True, "metrics": {"total_return_pct": 3}, "curve": [],
                        "spec_hash": "ab", "spec": {"entry": "SECRET-FORMULA"}, "summary": "s", "rules": []}]}
    execute("INSERT INTO benchmarks (id, agent_id, owner_id, steps_text, symbol, interval, data_hash, result_json,"
            " created_at) VALUES ('bm_1', ?, ?, '', 'fake:BTCUSDT', '1h', 'h', ?, 1)",
            (agent_id, seller["id"], json.dumps(result)))
    with pytest.raises(LabError):
        market.attach_benchmark(make_seller("Eve", "eve@example.com")["id"], listing["id"], "bm_1")
    market.attach_benchmark(seller["id"], listing["id"], "bm_1")
    benchmark = market.listing_detail(listing["id"])["benchmark"]
    assert benchmark["rows"] == [{"model": "gemini:x", "ok": True, "metrics": {"total_return_pct": 3}, "curve": [],
                                  "spec_hash": "ab"}]
    assert "SECRET-FORMULA" not in dump(benchmark)


def test_routes_for_listings(seller_client, buyer_client, manager):
    fake_provider()
    seller = flow_seller()
    version, proof = make_proof(seller, "fake:BTCUSDT", "1h")
    body = {"version_id": version["id"], "title": "Route Agent", "pitch": "p", "price_cents": 2500, "mode": "hold",
            "trial_s": 120, "min_return_bps": 0, "max_loss_bps": 500, "proof_id": proof["id"],
            "allow_test_drive": True}
    assert buyer_client.post("/api/listings", json=body).status_code == 403
    created = seller_client.post("/api/listings", json=body)
    assert created.status_code == 200
    listing_id = created.json()["id"]
    assert created.json()["proof"]["metrics"]["trades"] == created.json()["headline"]["trades"]
    assert [item["id"] for item in buyer_client.get("/api/listings?kind=crypto&sort=price").json()] == [listing_id]
    assert buyer_client.post(f"/api/listings/{listing_id}/pause").status_code == 403
    assert seller_client.post(f"/api/listings/{listing_id}/pause").json()["active"] is False
    assert seller_client.post(f"/api/listings/{listing_id}/resume").json()["active"] is True
    rerun = buyer_client.post(f"/api/listings/{listing_id}/rerun", json={})
    assert rerun.status_code == 200 and rerun.json()["match"] is True
    drive = buyer_client.post(f"/api/listings/{listing_id}/test-drive", json={"symbol": "fake:ETHUSDT"})
    assert drive.status_code == 200 and drive.json()["proof"]["kind"] == "testdrive"
    assert buyer_client.get(f"/api/listings/{listing_id}/diligence").json()["facts"]["reruns_matched"] == 1
    assert entry_formula(None) not in dump(buyer_client.get(f"/api/listings/{listing_id}").json())


def test_unauthenticated_listing_creation_is_401_with_code(client):
    response = client.post("/api/listings", json={"version_id": "v_x", "title": "abc", "price_cents": 500,
                                                  "proof_id": "pf_x"})
    assert response.status_code == 401 and response.json()["code"] == "unauthorized"


def test_test_drive_can_be_turned_off(seller_client, buyer_client, manager):
    seller = flow_seller()
    listing = make_listing(seller, allow_test_drive=False)
    response = buyer_client.post(f"/api/listings/{listing['id']}/test-drive", json={})
    assert response.status_code == 403 and response.json()["code"] == "test_drive_off"


def test_private_data_symbols_never_reach_money_deciding_runs(manager):
    from parable.live_symbols import is_live_symbol, require_instant_mode, require_live_symbol

    for symbol in ("upload:d_ab12cd34ef", "sample:BTCUSDT"):
        assert is_live_symbol(symbol) is False
        with pytest.raises(LabError) as problem:
            require_instant_mode(symbol, "hold")
        assert problem.value.code == "bad_request"
        with pytest.raises(LabError):
            require_live_symbol(symbol, "a hold trial")
        require_instant_mode(symbol, "instant")
    assert is_live_symbol("binance:BTCUSDT") and is_live_symbol("fake:BTCUSDT")
    seller = make_seller()
    version, proof = make_proof(seller, "sample:BTCUSDT", "1h")
    listing = new_listing_for(seller, version["id"], proof["id"], mode="instant")
    assert listings.start_track(listing) is None
    execute("UPDATE listings SET symbol = 'upload:d_ab12cd34ef' WHERE id = ?", (listing["id"],))
    assert listings.ensure_tracks() == 0
    assert rows("SELECT id FROM runs") == []


def test_paused_listing_is_hidden_from_everyone_but_its_owner(seller_client, buyer_client, manager):
    fake_provider()
    seller = flow_seller()
    listing = make_listing(seller)
    path = f"/api/listings/{listing['id']}"
    assert buyer_client.get(path).status_code == 200
    assert seller_client.post(f"{path}/pause").json()["active"] is False
    for method, url in (("get", path), ("get", f"{path}/diligence"), ("post", f"{path}/rerun"),
                        ("post", f"{path}/test-drive")):
        response = getattr(buyer_client, method)(url)
        assert response.status_code == 404 and response.json()["code"] == "not_found"
    assert seller_client.get(path).status_code == 200
    assert seller_client.get(f"{path}/diligence").status_code == 200
    assert seller_client.post(f"{path}/resume").json()["active"] is True
    assert buyer_client.get(path).status_code == 200


def test_every_early_track_death_counts_except_a_pause(manager):
    seller = make_seller()
    listing = make_listing(seller)
    referee.stop(listing["track_run_id"], "stopped")
    assert listings.ensure_tracks() == 1
    track = market.listing_summary(listing["id"])["track"]
    assert track["runs_total"] == 2 and track["runs_ended_early"] == 1
    market.pause_listing(seller["id"], listing["id"])
    market.resume_listing(seller["id"], listing["id"])
    track = market.listing_summary(listing["id"])["track"]
    assert track["runs_total"] == 3 and track["runs_ended_early"] == 1
    assert referee.seller_record(seller["id"])["track_ended_early"] == 1
    execute("UPDATE runs SET status = 'dead', cause = NULL, final_equity_usd = start_cash_usd WHERE id = ?", (track["run_id"],))
    assert market.listing_summary(listing["id"])["track"]["runs_ended_early"] == 2
