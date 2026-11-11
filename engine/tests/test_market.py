import json

import pytest

from market_support import approve_and_confirm, expire_run, make_listing, make_seller, purchase_row
from parable import analyst, ledger, market, referee, settlement, settlement_text
from parable.db import execute, one
from parable.errors import MarketError
from parable.paypal import get_paypal

BUYER = ("Bo Buyer", "bo@example.com")


def begin(listing=None, **options):
    return approve_and_confirm(market.start_purchase((listing or make_listing(**options))["id"],
                                                     make_seller(*BUYER)["id"]))


def test_stopping_a_trial_run_voids_the_hold(manager, settled):
    purchase = begin()
    manager.stop(purchase["run_id"])
    done = settled(purchase["id"], ("voided", "error"))
    assert done["status"] == "voided" and json.loads(done["verdict_json"])["cause"] == "stopped"


def test_loss_limit_voids_and_never_charges(manager, settled):
    purchase = begin()
    referee.stop(purchase["run_id"], "loss_limit")
    done = settled(purchase["id"], ("voided",))
    assert json.loads(done["verdict_json"])["cause"] == "loss_limit" and not done["paypal_capture_id"]
    assert [e["kind"] for e in ledger.entries(subject=f"purchase:{purchase['id']}")][0] == "payment.voided"


def test_survival_below_promised_return_still_fails(manager, settled):
    purchase = begin(min_return_bps=100)
    expire_run(purchase["run_id"])
    done = settled(purchase["id"], ("voided",))
    verdict = json.loads(done["verdict_json"])
    assert verdict["cause"] == "expired" and verdict["passed"] is False and verdict["return_bps"] == 0


def test_settlement_runs_once_even_if_ended_twice(manager, settled):
    purchase = begin()
    expire_run(purchase["run_id"])
    settled(purchase["id"], ("paid_out",))
    run = referee.get_run(purchase["run_id"])
    settlement.settle_run(run)
    settlement.settle_run(run)
    assert len(ledger.entries(kind="payment.captured")) == 1 and len(ledger.entries(kind="payout.sent")) == 1


def test_paypal_error_marks_error_and_retry_recovers(manager, settled):
    purchase = begin()
    get_paypal().fail_next("capture_authorization", "SERVICE_UNAVAILABLE")
    expire_run(purchase["run_id"])
    failed = settled(purchase["id"], ("error",))
    assert "SERVICE_UNAVAILABLE" in failed["error"] and json.loads(failed["verdict_json"])["passed"] is True
    with pytest.raises(MarketError):
        market.retry_settlement(begin(title="Other")["id"])
    recovered = market.retry_settlement(purchase["id"])
    assert recovered["status"] == "paid_out" and recovered["error"] is None
    assert len(ledger.entries(kind="payment.captured")) == 1


def test_retry_after_failed_payout_does_not_capture_twice(manager, settled):
    purchase = begin()
    get_paypal().fail_next("create_payout", "INTERNAL_SERVICE_ERROR")
    expire_run(purchase["run_id"])
    assert settled(purchase["id"], ("error",))["status"] == "error"
    assert purchase_row(purchase["id"])["paypal_capture_id"]
    assert market.retry_settlement(purchase["id"])["status"] == "paid_out"
    assert len(ledger.entries(kind="payment.captured")) == 1


def test_retry_restarts_a_trial_that_never_started(manager, monkeypatch):
    purchase = begin()
    execute("UPDATE purchases SET status = 'error', run_id = NULL WHERE id = ?", (purchase["id"],))
    assert market.retry_settlement(purchase["id"])["status"] == "probation"


def test_cancel_unapproved_only_touches_stale_created_purchases(manager):
    buyer = make_seller(*BUYER)
    stale = market.start_purchase(make_listing(title="One")["id"], buyer["id"])
    fresh = market.start_purchase(make_listing(title="Two")["id"], buyer["id"])
    approved = begin(title="Three")
    execute("UPDATE purchases SET created_at = created_at - 4 * 3600 WHERE id IN (?, ?)",
            (stale["purchase_id"], approved["id"]))
    assert market.cancel_unapproved() == 1
    assert purchase_row(stale["purchase_id"])["status"] == "cancelled"
    assert purchase_row(fresh["purchase_id"])["status"] == "created"
    assert purchase_row(approved["id"])["status"] == "probation"
    with pytest.raises(MarketError, match="cancelled"):
        market.confirm_approval(stale["purchase_id"], stale["paypal_order_id"])


def test_purchase_views_hide_license_until_paid_and_mask_paypal_ids(manager, settled):
    purchase = begin()
    buyer_id = purchase["buyer_id"]
    live = market.get_purchase(purchase["id"], buyer_id)
    assert live["license"] is None and live["status"] == "probation" and live["run"]["seconds_left"] > 0
    expire_run(purchase["run_id"])
    settled(purchase["id"], ("paid_out",))
    view = market.get_purchase(purchase["id"], buyer_id)
    assert view["license"]["key"].startswith("pk_") and view["license"]["spec"]["entry"]
    order = purchase_row(purchase["id"])["paypal_order_id"]
    assert view["paypal_order_id"].startswith("***") and view["paypal_order_id"][-6:] == order[-6:]
    assert view["payout_cents"] == 1800 and view["threshold"] == {"min_return_bps": -50, "max_loss_bps": 1000}
    assert "buyer_email" not in view and view["run"]["status"] == "dead" and "rules" not in view["run"]
    assert [entry["seq"] for entry in view["timeline"]] == sorted(entry["seq"] for entry in view["timeline"])
    assert view["verdict"]["passed"] is True and view["verdict"]["explanation"]


def test_market_stats_track_holds_and_outcomes(manager, settled):
    assert market.market_stats()["held_cents"] == 0
    win = begin(make_listing(price_cents=2000, title="Win"))
    lose = begin(make_listing(price_cents=1000, title="Lose"))
    stats = market.market_stats()
    assert stats["held_cents"] == 3000 and stats["probations_running"] == 2 and stats["tracks_running"] == 2
    assert (stats["agents"], stats["proofs"], stats["reruns"]) == (2, 2, 0)
    referee.stop(lose["run_id"], "loss_limit")
    settled(lose["id"], ("voided",))
    expire_run(win["run_id"])
    settled(win["id"], ("paid_out",))
    stats = market.market_stats()
    assert (stats["passed"], stats["failed"], stats["held_cents"]) == (1, 1, 0)
    assert (stats["captured_cents"], stats["voided_cents"], stats["paid_out_cents"]) == (2000, 1000, 1800)
    assert stats["ledger_head"]["seq"] == ledger.head()["seq"]
    assert "eth_price_usd" not in stats


def test_ai_explanation_is_used_only_when_sane(monkeypatch):
    verdict = {"passed": False, "cause": "loss_limit", "return_bps": -200, "min_return_bps": 0, "lifetime_s": 30,
               "trades": 4, "refusals": 0}
    listing = {"title": "Agent", "trial_s": 600}
    good = "The agent hit its loss limit after 30 seconds, so the hold was released and nothing was taken."
    monkeypatch.setattr(analyst, "ask", lambda prompt: {"explanation": good})
    assert settlement_text.explain(verdict, listing) == good
    for bad in ({"explanation": "The payment was captured and paid out."}, {"explanation": "ok"},
                {"explanation": 7}, {"nope": 1}, None):
        monkeypatch.setattr(analyst, "ask", lambda prompt, bad=bad: bad)
        text = settlement_text.explain(verdict, listing)
        assert "loss limit" in text and "never charged" in text


def test_verdict_does_not_depend_on_the_ai(manager, settled, monkeypatch):
    monkeypatch.setattr(analyst, "ask", lambda prompt: {"explanation": "Everything is fine and the agent is great."})
    purchase = begin(min_return_bps=100)
    expire_run(purchase["run_id"])
    done = settled(purchase["id"], ("voided",))
    assert json.loads(done["verdict_json"])["passed"] is False and done["status"] == "voided"


def test_webhooks_reconcile_payout_and_capture(manager, settled):
    purchase = begin()
    expire_run(purchase["run_id"])
    settled(purchase["id"], ("paid_out",))
    raw = purchase_row(purchase["id"])
    market.on_webhook("PAYMENT.PAYOUTS-ITEM.UNCLAIMED", {
        "payout_batch_id": raw["paypal_payout_batch_id"], "transaction_status": "UNCLAIMED"})
    after = purchase_row(purchase["id"])
    assert after["payout_status"] == "UNCLAIMED" and "unclaimed" in after["error"]
    market.on_webhook("PAYMENT.PAYOUTSBATCH.SUCCESS", {"batch_header": {
        "payout_batch_id": raw["paypal_payout_batch_id"], "batch_status": "SUCCESS"}})
    assert purchase_row(purchase["id"])["payout_status"] == "SUCCESS"
    market.on_webhook("PAYMENT.CAPTURE.DENIED", {"id": raw["paypal_capture_id"]})
    denied = purchase_row(purchase["id"])
    assert denied["status"] == "error" and denied["paypal_capture_id"] is None
    logged = ledger.entries(kind="webhook.received")
    assert len(logged) == 3 and logged[0]["data"]["purchase_id"] == purchase["id"]


def test_webhook_for_unknown_resource_is_only_logged():
    market.on_webhook("PAYMENT.AUTHORIZATION.CREATED", {"id": "NOT-OURS"})
    entry = ledger.entries(kind="webhook.received")[0]
    assert entry["subject"] == "webhook" and entry["data"]["purchase_id"] is None


def test_install_registers_the_listener_and_the_track_hook(manager):
    assert settlement.on_run_ended in manager.listeners
    assert market.poll_tracks in manager.poll_hooks
    market.install(manager)
    assert manager.listeners.count(settlement.on_run_ended) == 1 and manager.poll_hooks.count(market.poll_tracks) == 1


def test_get_purchase_of_someone_else_is_not_found(manager):
    purchase = begin()
    with pytest.raises(Exception) as problem:
        market.get_purchase(purchase["id"], make_seller("Eve", "eve@example.com")["id"])
    assert problem.value.status == 404
    assert one("SELECT COUNT(*) AS n FROM purchases")["n"] == 1
