import pytest
from fastapi.testclient import TestClient

from market_support import make_listing, make_seller, purchase_row
from parable import ledger, market, referee
from parable.lab import llm
from parable.paypal import PayPalError, get_paypal
from parable.purchases import confirm_instant
from parable.run_views import public_run, run_visible
from parable.db import execute


def test_ledger_does_not_carry_the_paypal_order_id(manager):
    listing = make_listing()
    buyer = make_seller("Bo", "bo@example.com")
    started = market.start_purchase(listing["id"], buyer["id"])
    entry = ledger.entries(kind="purchase.created")[0]
    assert "paypal_order_id" not in entry["data"] and started["paypal_order_id"] not in str(entry)


def test_cancel_and_return_need_the_buyer_session(buyer_client, seller_client, client):
    listing = make_listing(seller=None, mode="instant", symbol="sample:BTCUSDT")
    started = buyer_client.post("/api/purchases", json={"listing_id": listing["id"]}).json()
    pid = started["purchase_id"]
    stranger = TestClient(client.app)
    assert stranger.get(f"/paypal/cancel?purchase={pid}", follow_redirects=False).status_code == 302
    assert purchase_row(pid)["status"] == "created"
    assert seller_client.get(f"/paypal/cancel?purchase={pid}", follow_redirects=False).status_code == 302
    assert purchase_row(pid)["status"] == "created"
    buyer_client.get(f"/paypal/cancel?purchase={pid}", follow_redirects=False)
    assert purchase_row(pid)["status"] == "cancelled"


def test_run_started_entries_hide_the_version_id(manager):
    listing = make_listing()
    started = ledger.entries(kind="run.started")[0]["data"]
    assert "version_id" not in started and "version_id" not in started["rules"]
    assert started["spec_hash"]


def test_practice_and_private_runs_are_hidden_from_others(manager):
    listing = make_listing()
    owner, other = listing["seller_id"], make_seller("Other", "other@example.com")["id"]
    practice = manager.start_for_version(owner, listing["version_id"], "fake:BTCUSDT", "1h", "practice", "Secret draft")
    assert run_visible(practice, owner) and not run_visible(practice, other) and not run_visible(practice, None)
    track = referee.get_run(listing["track_run_id"])
    assert run_visible(track, None)
    execute("UPDATE listings SET active = 0 WHERE id = ?", (listing["id"],))
    assert not run_visible(track, None) and run_visible(track, owner)


def test_probation_runs_do_not_show_the_account_to_strangers():
    run = {"purpose": "probation", "seller_id": "s_x", "purchase_id": "p_x", "id": 1}
    assert public_run(run)["seller_id"] is None and public_run(run)["purchase_id"] is None
    assert public_run(run, "s_x")["seller_id"] == "s_x"
    assert public_run({**run, "purpose": "track"})["seller_id"] == "s_x"


def test_a_key_echoed_in_a_long_error_is_fully_redacted():
    key = "sk-LIVE-1234567890abcdef"
    text = "x" * 190 + key
    assert key[:6] not in llm.redact(text, key)[: llm.BODY_CHARS + 20]
    assert "AIzaSyABCDEFGHIJKLMNOP" not in llm.redact("token AIzaSyABCDEFGHIJKLMNOP here", None)


def test_unknown_payer_fails_closed_with_real_paypal(manager, monkeypatch):
    listing = make_listing(mode="instant", symbol="sample:BTCUSDT")
    buyer = make_seller("Bo", "bo@example.com")
    started = market.start_purchase(listing["id"], buyer["id"])
    get_paypal().approve(started["paypal_order_id"], payer_id="")
    monkeypatch.setattr("parable.purchases.is_mock", lambda: False)
    with pytest.raises(PayPalError) as refused:
        confirm_instant(purchase_row(started["purchase_id"]), listing)
    assert refused.value.name == "PAYER_UNKNOWN"
    assert purchase_row(started["purchase_id"])["status"] != "captured"


def test_public_listing_discloses_assumptions_and_data_window(manager):
    listing = make_listing()
    view = market.listing_detail(listing["id"])
    assert view["assumptions"] == {"fee_bps": 10.0, "slippage_bps": 5.0}
    assert view["data"]["bars"] > 0 and view["data"]["start"] < view["data"]["end"]
    assert view["verifiable"] is True and view["data_note"] == ""
    assert view["proof"]["assumptions"] == view["assumptions"]
    execute("UPDATE proofs SET source_kind = 'creator' WHERE id = ?", (listing["proof_id"],))
    flagged = market.listing_detail(listing["id"])
    assert flagged["verifiable"] is False and "cannot check" in flagged["data_note"]
