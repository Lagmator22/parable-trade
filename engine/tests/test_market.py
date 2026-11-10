import json

import pytest

from market_support import USD, approve_and_confirm, expire_run, listing_input, make_listing, make_seller
from parable import analyst, ledger, market, referee, settlement
from parable.db import execute, one
from parable.errors import MarketError
from parable.paypal import PayPalError, get_paypal


def test_create_listing_validates_and_writes_ledger():
    seller = make_seller()
    listing = make_listing(seller)
    assert listing["id"].startswith("l_") and listing["active"] is True
    assert listing["seller"] == {"id": seller["id"], "name": "Ada Seller", "verified": True}
    assert ledger.entries(kind="listing.created")[0]["subject"] == f"listing:{listing['id']}"
    with pytest.raises(MarketError, match="strategy"):
        make_listing(seller, strategy="astrology")
    with pytest.raises(MarketError, match="not available"):
        make_listing(seller, brain="claude:nope")


@pytest.mark.parametrize("field,value", [
    ("price_cents", 99), ("price_cents", 50_001), ("probation_s", 59), ("probation_s", 259_201),
    ("min_return_bps", 501), ("min_return_bps", -501), ("title", "ab"),
])
def test_listing_input_bounds(field, value):
    with pytest.raises(ValueError):
        listing_input(**{field: value})


def test_pause_is_owner_only_idempotent_and_hides_listing():
    owner, other = make_seller(), make_seller("Bob", "bob@example.com")
    listing = make_listing(owner)
    with pytest.raises(MarketError) as denied:
        market.pause_listing(other["id"], listing["id"])
    assert denied.value.status == 403
    assert market.pause_listing(owner["id"], listing["id"])["active"] is False
    market.pause_listing(owner["id"], listing["id"])
    assert len(ledger.entries(kind="listing.paused")) == 1
    assert market.list_listings() == []
    assert len(market.list_listings(include_paused=True)) == 1
    with pytest.raises(MarketError) as missing:
        market.get_listing("l_missing")
    assert missing.value.status == 404


def test_practice_run_counts_on_record_and_is_limited(manager):
    owner, other = make_seller(), make_seller("Bob", "bob@example.com")
    listing = make_listing(owner)
    with pytest.raises(MarketError) as denied:
        market.start_practice(other["id"], listing["id"])
    assert denied.value.status == 403
    started = [market.start_practice(owner["id"], listing["id"]) for _ in range(3)]
    assert all(run["purpose"] == "practice" and run["listing_id"] == listing["id"] for run in started)
    with pytest.raises(MarketError) as limited:
        market.start_practice(owner["id"], listing["id"])
    assert limited.value.status == 429
    manager.stop(started[0]["id"])
    assert market.get_listing(listing["id"])["seller_record"]["practice_runs"] == 3
    assert len(market.listing_runs(listing["id"])) == 3


def test_start_purchase_stores_only_a_token_hash_and_fee(manager):
    listing = make_listing(price_cents=2550)
    started = market.start_purchase(listing["id"])
    stored = one("SELECT * FROM purchases WHERE id = ?", (started["purchase_id"],))
    assert stored["status"] == "created" and stored["amount_cents"] == 2550 and stored["fee_cents"] == 255
    assert started["buyer_token"] not in json.dumps(stored)
    assert started["approve_url"].endswith(f"order={started['paypal_order_id']}")
    assert ledger.entries(subject=f"purchase:{started['purchase_id']}")[0]["kind"] == "purchase.created"
    market.pause_listing(listing["seller_id"], listing["id"])
    with pytest.raises(MarketError) as paused:
        market.start_purchase(listing["id"])
    assert paused.value.status == 409
    with pytest.raises(MarketError):
        market.start_purchase(make_listing()["id"], via="carrier-pigeon")


def test_confirm_approval_requires_paypal_approval_and_is_idempotent(manager):
    started = market.start_purchase(make_listing()["id"])
    with pytest.raises(PayPalError):
        market.confirm_approval(started["purchase_id"], started["paypal_order_id"])
    with pytest.raises(MarketError, match="does not belong"):
        market.confirm_approval(started["purchase_id"], "MOCK-ORDER-9999")
    first = approve_and_confirm(started)
    assert first["status"] == "probation" and first["run_id"]
    again = market.confirm_approval(started["purchase_id"], started["paypal_order_id"])
    assert again["run_id"] == first["run_id"] and again["paypal_authorization_id"] == first["paypal_authorization_id"]
    assert len(ledger.entries(kind="purchase.authorized")) == 1
    run = referee.get_run(first["run_id"])
    assert run["purpose"] == "probation" and run["purchase_id"] == started["purchase_id"]
    assert run["rules"]["lease_seconds"] == 120


def test_passing_probation_captures_pays_out_and_issues_license(manager, price_box, settled):
    started = market.start_purchase(make_listing(price_cents=2000)["id"])
    purchase = approve_and_confirm(started)
    assert expire_run(purchase["run_id"])["cause"] == "expired"
    done = settled(started["purchase_id"], ("paid_out", "error"))
    assert done["status"] == "paid_out" and done["verdict"]["passed"] is True
    stored = one("SELECT * FROM purchases WHERE id = ?", (started["purchase_id"],))
    assert stored["paypal_capture_id"] and stored["paypal_payout_batch_id"] and stored["license_key"].startswith("pk_")
    assert stored["payout_status"] == "SUCCESS"
    kinds = [entry["kind"] for entry in done["timeline"]]
    for kind in ("purchase.created", "purchase.authorized", "purchase.probation_started", "run.started",
                 "run.ended", "purchase.passed", "payment.captured", "payout.sent"):
        assert kind in kinds
    payout = ledger.entries(kind="payout.sent")[0]["data"]
    assert payout["amount_cents"] == 1800 and payout["fee_cents"] == 200
    assert ledger.verify()["ok"]


def test_loss_limit_voids_the_hold_and_never_charges(manager, price_box, settled):
    started = market.start_purchase(make_listing(max_loss_bps=100)["id"])
    purchase = approve_and_confirm(started)
    assert purchase["status"] == "probation"
    price_box.set(1500)
    assert referee.check(purchase["run_id"])["cause"] == "loss_limit"
    done = settled(started["purchase_id"], ("voided", "error"))
    assert done["status"] == "voided" and done["verdict"]["passed"] is False
    assert done["verdict"]["cause"] == "loss_limit"
    stored = one("SELECT * FROM purchases WHERE id = ?", (started["purchase_id"],))
    assert not stored["paypal_capture_id"] and not stored["license_key"]
    assert get_paypal().get_authorization(stored["paypal_authorization_id"])["status"] == "VOIDED"
    assert ledger.entries(kind="payment.voided") and not ledger.entries(kind="payment.captured")


def test_survival_below_promised_return_still_fails(manager, price_box, settled):
    listing = make_listing(max_loss_bps=5000, min_return_bps=500, max_trade_usd=100 * USD)
    purchase = approve_and_confirm(market.start_purchase(listing["id"]))
    expire_run(purchase["run_id"])
    done = settled(purchase["id"], ("voided", "paid_out", "error"))
    assert done["status"] == "voided"
    assert done["verdict"]["cause"] == "expired" and done["verdict"]["min_return_bps"] == 500


def test_stopping_a_probation_run_fails_the_purchase(manager, price_box, settled):
    purchase = approve_and_confirm(market.start_purchase(make_listing()["id"]))
    manager.stop(purchase["run_id"])
    done = settled(purchase["id"], ("voided", "error"))
    assert done["status"] == "voided" and done["verdict"]["cause"] == "stopped"


def test_settlement_runs_once_even_if_ended_twice(manager, price_box, settled):
    purchase = approve_and_confirm(market.start_purchase(make_listing()["id"]))
    expire_run(purchase["run_id"])
    settled(purchase["id"], ("paid_out",))
    run = referee.get_run(purchase["run_id"])
    settlement.settle_run(run)
    settlement.settle_run(run)
    assert len(ledger.entries(kind="payment.captured")) == 1 and len(ledger.entries(kind="payout.sent")) == 1


def test_paypal_error_marks_error_and_retry_recovers(manager, price_box, settled, monkeypatch):
    purchase = approve_and_confirm(market.start_purchase(make_listing()["id"]))
    real = get_paypal().capture_authorization

    def broken(*args, **kwargs):
        raise PayPalError(503, "SERVICE_UNAVAILABLE", "try later")

    monkeypatch.setattr(get_paypal(), "capture_authorization", broken)
    expire_run(purchase["run_id"])
    failed = settled(purchase["id"], ("error",))
    assert "SERVICE_UNAVAILABLE" in failed["error"] and failed["verdict"]["passed"] is True
    with pytest.raises(MarketError):
        market.retry_settlement(make_listing()["id"])
    monkeypatch.setattr(get_paypal(), "capture_authorization", real)
    recovered = market.retry_settlement(purchase["id"])
    assert recovered["status"] == "paid_out" and recovered["error"] is None
    assert len(ledger.entries(kind="payment.captured")) == 1


def test_retry_after_failed_payout_does_not_capture_twice(manager, price_box, settled, monkeypatch):
    purchase = approve_and_confirm(market.start_purchase(make_listing()["id"]))
    real = get_paypal().create_payout

    def broken(*args, **kwargs):
        raise PayPalError(500, "INTERNAL_SERVICE_ERROR", "down")

    monkeypatch.setattr(get_paypal(), "create_payout", broken)
    expire_run(purchase["run_id"])
    assert settled(purchase["id"], ("error",))["status"] == "error"
    assert one("SELECT paypal_capture_id FROM purchases WHERE id = ?", (purchase["id"],))["paypal_capture_id"]
    monkeypatch.setattr(get_paypal(), "create_payout", real)
    assert market.retry_settlement(purchase["id"])["status"] == "paid_out"
    assert len(ledger.entries(kind="payment.captured")) == 1


def test_cancel_unapproved_only_touches_stale_created_purchases(manager):
    stale = market.start_purchase(make_listing()["id"])
    fresh = market.start_purchase(make_listing()["id"])
    approved = approve_and_confirm(market.start_purchase(make_listing()["id"]))
    execute("UPDATE purchases SET created_at = created_at - 4 * 3600 WHERE id IN (?, ?)",
            (stale["purchase_id"], approved["id"]))
    assert market.cancel_unapproved() == 1
    assert market.get_purchase(stale["purchase_id"])["status"] == "cancelled"
    assert market.get_purchase(fresh["purchase_id"])["status"] == "created"
    assert market.get_purchase(approved["id"])["status"] == "probation"
    with pytest.raises(MarketError, match="cancelled"):
        market.confirm_approval(stale["purchase_id"], stale["paypal_order_id"])


def test_purchase_views_hide_license_and_mask_paypal_ids(manager, price_box, settled):
    started = market.start_purchase(make_listing()["id"])
    purchase = approve_and_confirm(started)
    expire_run(purchase["run_id"])
    settled(purchase["id"], ("paid_out",))
    public = market.get_purchase(purchase["id"])
    wrong = market.get_purchase(purchase["id"], "not-the-token")
    private = market.get_purchase(purchase["id"], started["buyer_token"])
    assert public["license"] is None and wrong["license"] is None
    assert private["license"]["key"].startswith("pk_") and private["license"]["bot"]["strategy"] == "yolo"
    assert private["license"]["fingerprint"].startswith("0x")
    assert public["paypal_order_id"].startswith("***") and public["paypal_order_id"][-6:] == started["paypal_order_id"][-6:]
    assert public["payout_cents"] == 1800 and public["threshold"]["min_return_bps"] == -50
    assert "buyer_email" not in public and public["run"]["status"] == "dead"
    assert len([e for e in public["timeline"] if e["kind"] == "run.trade"]) <= 20
    sequence = [entry["seq"] for entry in public["timeline"]]
    assert sequence == sorted(sequence)


def test_live_run_view_has_equity_and_countdown(manager, price_box):
    purchase = approve_and_confirm(market.start_purchase(make_listing()["id"]))
    view = market.get_purchase(purchase["id"])
    assert view["status"] == "probation" and view["run"]["seconds_left"] > 0
    assert "equity_usd" in view["run"] and "pnl_bps" in view["run"] and "rules_json" not in view["run"]
    with pytest.raises(MarketError):
        market.get_purchase("p_missing")


def test_market_stats_track_holds_and_outcomes(manager, price_box, settled):
    assert market.market_stats()["held_cents"] == 0
    win = approve_and_confirm(market.start_purchase(make_listing(price_cents=2000)["id"]))
    lose = approve_and_confirm(market.start_purchase(make_listing(price_cents=1000, max_loss_bps=100)["id"]))
    assert market.market_stats()["held_cents"] == 3000
    assert market.market_stats()["probations_running"] == 2
    price_box.set(1500)
    referee.check(lose["run_id"])
    settled(lose["id"], ("voided",))
    price_box.set(3000)
    expire_run(win["run_id"])
    settled(win["id"], ("paid_out",))
    stats = market.market_stats()
    assert (stats["passed"], stats["failed"], stats["held_cents"]) == (1, 1, 0)
    assert (stats["captured_cents"], stats["voided_cents"], stats["paid_out_cents"]) == (2000, 1000, 1800)
    assert stats["ledger_head"]["seq"] == ledger.head()["seq"]


def test_ai_explanation_is_used_only_when_sane(monkeypatch):
    verdict = {"passed": False, "cause": "loss_limit", "return_bps": -200, "min_return_bps": 0, "lifetime_s": 30,
               "trades": 4, "refusals": 0}
    listing = {"title": "Bot", "probation_s": 600}
    good = "The bot hit its loss limit after 30 seconds, so the hold was released and nothing was taken."
    monkeypatch.setattr(analyst, "ask", lambda prompt: {"explanation": good})
    assert settlement.explain(verdict, listing) == good
    for bad in ({"explanation": "The payment was captured and paid out."}, {"explanation": "ok"}, {"explanation": 7},
                {"nope": 1}, None):
        monkeypatch.setattr(analyst, "ask", lambda prompt, bad=bad: bad)
        assert "loss limit" in settlement.explain(verdict, listing) and "never charged" in settlement.explain(verdict, listing)


def test_verdict_does_not_depend_on_the_ai(manager, price_box, settled, monkeypatch):
    monkeypatch.setattr(analyst, "ask", lambda prompt: {"explanation": "Everything is fine and the bot is great."})
    listing = make_listing(max_loss_bps=100)
    purchase = approve_and_confirm(market.start_purchase(listing["id"]))
    price_box.set(1500)
    referee.check(purchase["run_id"])
    done = settled(purchase["id"], ("voided",))
    assert done["verdict"]["passed"] is False and done["status"] == "voided"


def test_webhooks_reconcile_payout_and_capture(manager, price_box, settled):
    purchase = approve_and_confirm(market.start_purchase(make_listing()["id"]))
    expire_run(purchase["run_id"])
    done = settled(purchase["id"], ("paid_out",))
    raw = one("SELECT * FROM purchases WHERE id = ?", (purchase["id"],))
    market.on_webhook("PAYMENT.PAYOUTS-ITEM.UNCLAIMED", {
        "payout_batch_id": raw["paypal_payout_batch_id"], "transaction_status": "UNCLAIMED"})
    after = one("SELECT * FROM purchases WHERE id = ?", (purchase["id"],))
    assert after["payout_status"] == "UNCLAIMED" and "unclaimed" in after["error"]
    market.on_webhook("PAYMENT.PAYOUTSBATCH.SUCCESS", {"batch_header": {
        "payout_batch_id": raw["paypal_payout_batch_id"], "batch_status": "SUCCESS"}})
    assert one("SELECT payout_status FROM purchases WHERE id = ?", (purchase["id"],))["payout_status"] == "SUCCESS"
    market.on_webhook("PAYMENT.CAPTURE.DENIED", {"id": raw["paypal_capture_id"]})
    denied = one("SELECT * FROM purchases WHERE id = ?", (purchase["id"],))
    assert denied["status"] == "error" and denied["paypal_capture_id"] is None
    logged = ledger.entries(kind="webhook.received")
    assert len(logged) == 3 and logged[0]["data"]["purchase_id"] == purchase["id"] and done


def test_webhook_for_unknown_resource_is_only_logged():
    market.on_webhook("PAYMENT.AUTHORIZATION.CREATED", {"id": "NOT-OURS"})
    entry = ledger.entries(kind="webhook.received")[0]
    assert entry["subject"] == "webhook" and entry["data"]["purchase_id"] is None
