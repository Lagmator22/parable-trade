import pytest
from pydantic import ValidationError

from market_support import make_listing, make_proof, make_seller
from parable import market, proofs, referee
from parable.db import execute
from parable.errors import LabError
from parable.models import NewListing
from parable.settlement_text import build_verdict, template_explanation


def run_row(**overrides) -> dict:
    base = {"cause": "expired", "start_cash_usd": 1000, "final_equity_usd": 1000, "lifetime_s": 600,
            "trades": 0, "refusals": 0, "bars_seen": 0}
    return {**base, **overrides}


def test_zero_trades_cannot_pass():
    verdict = build_verdict(run_row(bars_seen=20), 0)
    assert verdict["passed"] is False
    assert "no trades" in template_explanation(verdict, 600)


def test_too_few_bars_cannot_pass():
    verdict = build_verdict(run_row(trades=2, bars_seen=1), 0)
    assert verdict["passed"] is False
    assert "too few" in template_explanation(verdict, 600)


def test_active_run_that_meets_the_floor_passes():
    assert build_verdict(run_row(trades=2, bars_seen=10, final_equity_usd=1010), 0)["passed"] is True


def test_trial_must_cover_ten_bars():
    seller = make_seller()
    version, proof = make_proof(seller, "fake:BTCUSDT", "1h")
    with pytest.raises(LabError) as short:
        market.create_listing(seller["id"], NewListing(
            version_id=version["id"], title="Too short", price_cents=500, mode="hold", trial_s=600,
            proof_id=proof["id"]))
    assert short.value.status == 400


def test_negative_floor_is_rejected():
    with pytest.raises(ValidationError):
        NewListing(version_id="v", title="Negative", price_cents=500, min_return_bps=-100, proof_id="p")


def test_seller_and_anonymous_reruns_are_not_counted():
    listing = make_listing()
    owner = listing["seller_id"]
    for who in (owner, owner, "v_aaaaaaaaaaaaaaaa", "v_bbbbbbbbbbbbbbbb"):
        proofs.rerun_listing(listing["id"], who)
    counts = market.listing_summary(listing["id"])["reruns"]
    assert counts["count"] == 0 and counts["by_seller"] == 2 and counts["anonymous"] == 2


def test_each_account_counts_once():
    listing = make_listing()
    checker = make_seller("Checker", "checker@example.com")
    for _ in range(3):
        proofs.rerun_listing(listing["id"], checker["id"])
    counts = market.listing_summary(listing["id"])["reruns"]
    assert counts["count"] == 1 and counts["matched"] == 1


def test_creator_data_reruns_are_not_counted():
    listing = make_listing()
    checker = make_seller("Checker", "checker@example.com")
    proofs.rerun_listing(listing["id"], checker["id"])
    execute("UPDATE proofs SET source_kind = 'creator' WHERE listing_id = ? AND kind = 'rerun'", (listing["id"],))
    assert market.listing_summary(listing["id"])["reruns"]["count"] == 0


def test_practice_runs_do_not_enter_the_seller_record(manager):
    listing = make_listing()
    seller = listing["seller_id"]
    before = referee.seller_record(seller)
    practice = manager.start_for_version(seller, listing["version_id"], "fake:BTCUSDT", "1h", "practice", "p")
    referee.stop(practice["id"], "expired")
    after = referee.seller_record(seller)
    assert after["ended"] == before["ended"] and after["survived"] == before["survived"]
    assert after["practice_runs"] == before["practice_runs"] + 1
