import pytest

from market_support import make_listing, make_seller, set_headline
from parable import analyst, shopper


@pytest.fixture
def market_of_three():
    proven, shaky, newcomer = make_seller("Proven", "p@example.com"), make_seller("Shaky", "s@example.com"), make_seller("New", "n@example.com")
    listings = {
        "proven": make_listing(proven, title="Proven Agent", price_cents=3000),
        "shaky": make_listing(shaky, title="Shaky Agent", price_cents=1000),
        "new": make_listing(newcomer, title="New Agent", price_cents=500),
    }
    set_headline(listings["proven"], total_return_pct=40.0, benchmark_return_pct=10.0, max_drawdown_pct=10.0)
    set_headline(listings["shaky"], total_return_pct=5.0, benchmark_return_pct=10.0, max_drawdown_pct=35.0)
    set_headline(listings["new"], total_return_pct=20.0, benchmark_return_pct=10.0, max_drawdown_pct=12.0)
    return listings


def test_fallback_prefers_the_best_excess_return(market_of_three):
    answer = shopper.recommend("something that beats the market")
    assert answer["listing_id"] == market_of_three["proven"]["id"] and answer["by"] == "rules"
    assert "+40.0%" in answer["reason"] and "buy and hold" in answer["reason"]
    assert set(answer["alternatives"]) <= {market_of_three["shaky"]["id"], market_of_three["new"]["id"]}
    assert market_of_three["proven"]["id"] not in answer["alternatives"]


def test_matched_reruns_lift_the_ranking(market_of_three):
    from parable import proofs

    for number in range(20):
        checker = make_seller(f"Checker {number}", f"checker{number}@example.com")
        proofs.rerun_listing(market_of_three["new"]["id"], checker["id"])
    assert shopper.recommend("anything")["listing_id"] == market_of_three["new"]["id"]


def test_budget_filters_candidates(market_of_three):
    answer = shopper.recommend("anything", budget_cents=1500)
    assert answer["listing_id"] in (market_of_three["shaky"]["id"], market_of_three["new"]["id"])


def test_nothing_affordable_returns_no_listing(market_of_three):
    answer = shopper.recommend("anything", budget_cents=100)
    assert answer["listing_id"] is None and answer["alternatives"] == [] and "budget" in answer["reason"]


def test_empty_market_returns_no_listing():
    assert shopper.recommend("an agent")["listing_id"] is None


def test_cautious_wording_weights_drawdown(market_of_three):
    set_headline(market_of_three["proven"], max_drawdown_pct=45.0)
    assert shopper.recommend("the best")["listing_id"] == market_of_three["proven"]["id"]
    assert shopper.recommend("a low-risk agent")["listing_id"] == market_of_three["new"]["id"]


def test_compact_facts_for_the_ai_hold_no_spec(market_of_three):
    from parable.listing_views import list_listings

    compact = shopper.compact(list_listings()[0])
    assert set(compact) >= {"asset", "kind", "data_badge", "mode", "price_dollars", "proof_return_percent",
                            "reruns_matched", "live_track_percent"}
    assert "entry" not in str(compact) and compact["data_badge"] == "market data"


def test_valid_ai_pick_is_used(market_of_three, monkeypatch):
    pick, other = market_of_three["shaky"]["id"], market_of_three["new"]["id"]
    monkeypatch.setattr(analyst, "ask", lambda prompt: {"listing_id": pick, "reason": "It is the cheapest proven-ish bot.",
                                                         "alternatives": [other, other, "l_made_up", pick]})
    answer = shopper.recommend("cheap")
    assert answer["listing_id"] == pick and answer["alternatives"] == [other]
    assert answer["by"] == analyst.brain_name()


def test_prompt_lists_only_candidates_within_budget(market_of_three, monkeypatch):
    seen = []
    monkeypatch.setattr(analyst, "ask", lambda prompt: seen.append(prompt))
    shopper.recommend("budget", budget_cents=1500)
    assert market_of_three["proven"]["id"] not in seen[0] and market_of_three["shaky"]["id"] in seen[0]


@pytest.mark.parametrize("answer", [
    None, {}, {"listing_id": "l_invented", "reason": "fine"}, {"listing_id": None, "reason": "fine"},
    {"listing_id": "PLACEHOLDER", "reason": ""}, {"listing_id": "PLACEHOLDER", "reason": 5},
    {"listing_id": "PLACEHOLDER", "reason": "ok", "alternatives": "x"},
    {"listing_id": "PLACEHOLDER", "reason": "ok", "alternatives": [1]},
    {"listing_id": "PLACEHOLDER", "reason": "r" * 900},
])
def test_invalid_ai_answers_use_the_fallback(market_of_three, monkeypatch, answer):
    if answer and answer.get("listing_id") == "PLACEHOLDER":
        answer = {**answer, "listing_id": market_of_three["proven"]["id"]}
    monkeypatch.setattr(analyst, "ask", lambda prompt: answer)
    assert shopper.recommend("q")["by"] == "rules"


def test_query_is_trimmed_and_none_safe(market_of_three):
    assert shopper.recommend(None)["listing_id"]
    assert shopper.recommend("x" * 5000)["listing_id"]
