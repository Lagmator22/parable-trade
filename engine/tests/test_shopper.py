import pytest

from market_support import make_listing, make_seller
from parable import analyst, referee, shopper
from parable.models import BotRules


def record_runs(seller: dict, listing: dict, survived: int, died: int) -> None:
    rules = BotRules.model_validate(listing["rules"])
    for index in range(survived + died):
        run = referee.open_run(seller["id"], rules, "practice", "p", listing_id=listing["id"])
        referee.stop(run["id"], "expired" if index < survived else "loss_limit")


@pytest.fixture
def market_of_three(price_box):
    proven, shaky, newcomer = make_seller("Proven", "p@example.com"), make_seller("Shaky", "s@example.com"), make_seller("New", "n@example.com")
    listings = {
        "proven": make_listing(proven, title="Proven Bot", price_cents=3000, max_loss_bps=200),
        "shaky": make_listing(shaky, title="Shaky Bot", price_cents=1000, max_loss_bps=800),
        "new": make_listing(newcomer, title="New Bot", price_cents=500, max_loss_bps=300),
    }
    record_runs(proven, listings["proven"], 5, 0)
    record_runs(shaky, listings["shaky"], 1, 4)
    return listings


def test_fallback_prefers_the_best_survival_record(market_of_three):
    answer = shopper.recommend("something that survives")
    assert answer["listing_id"] == market_of_three["proven"]["id"] and answer["by"] == "rules"
    assert "5 of 5 runs survived" in answer["reason"]
    assert set(answer["alternatives"]) <= {market_of_three["shaky"]["id"], market_of_three["new"]["id"]}
    assert market_of_three["proven"]["id"] not in answer["alternatives"]


def test_budget_filters_candidates(market_of_three):
    answer = shopper.recommend("anything", budget_cents=1500)
    assert answer["listing_id"] != market_of_three["proven"]["id"]
    assert answer["listing_id"] in (market_of_three["shaky"]["id"], market_of_three["new"]["id"])


def test_nothing_affordable_returns_no_listing(market_of_three):
    answer = shopper.recommend("anything", budget_cents=100)
    assert answer["listing_id"] is None and answer["alternatives"] == [] and "budget" in answer["reason"]


def test_empty_market_returns_no_listing():
    assert shopper.recommend("a bot")["listing_id"] is None


def test_cautious_wording_prefers_a_tighter_loss_limit(price_box):
    one, two = make_seller("One", "1@example.com"), make_seller("Two", "2@example.com")
    loose = make_listing(one, title="Loose", max_loss_bps=1000)
    tight = make_listing(two, title="Tight", max_loss_bps=100)
    for owner, listing in ((one, loose), (two, tight)):
        record_runs(owner, listing, 4, 0)
    assert shopper.recommend("a low-risk bot")["listing_id"] == tight["id"]


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
