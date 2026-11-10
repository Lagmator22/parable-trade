import pytest

from market_support import expire_run, make_listing, make_seller
from parable import analyst, diligence, referee
from parable.errors import MarketError
from parable.models import BotRules


@pytest.fixture(autouse=True)
def fresh_cache():
    diligence.clear_cache()
    yield
    diligence.clear_cache()


def finished_run(seller: dict, listing: dict, cause: str = "expired") -> dict:
    rules = BotRules.model_validate(listing["rules"])
    run = referee.open_run(seller["id"], rules, "practice", "practice", listing_id=listing["id"])
    if cause == "expired":
        return expire_run(run["id"]) or run
    return referee.stop(run["id"], "loss_limit")


def ai_answer(**overrides) -> dict:
    base = {"risk": "low", "headline": "Solid record with 4 of 4 runs surviving.",
            "findings": ["All 4 finished runs survived.", "Average return was +0.00%.", "No refusals were seen."],
            "red_flags": []}
    return {**base, **overrides}


def test_unknown_listing_is_a_404():
    with pytest.raises(MarketError) as missing:
        diligence.report("l_nothing")
    assert missing.value.status == 404


def test_thin_record_is_flagged_and_not_low_risk():
    report = diligence.report(make_listing()["id"])
    assert report["by"] == "rules" and report["risk"] in ("medium", "high")
    assert report["facts"]["thin_record"] is True
    assert any("Thin record" in flag for flag in report["red_flags"])
    assert "no finished runs" in report["findings"][0]


def test_strong_record_is_low_risk_with_facts(price_box):
    seller = make_seller()
    listing = make_listing(seller, min_return_bps=0)
    for _ in range(4):
        finished_run(seller, listing)
    report = diligence.report(listing["id"])
    assert report["risk"] == "low" and report["red_flags"] == []
    assert report["facts"]["survived"] == 4 and report["facts"]["survival_rate"] == 1.0
    assert report["headline"].startswith("Low risk") and 3 <= len(report["findings"]) <= 5


def test_deaths_raise_risk_and_list_loss_limit_red_flag(price_box):
    seller = make_seller()
    listing = make_listing(seller)
    for cause in ("expired", "loss_limit", "loss_limit", "loss_limit"):
        finished_run(seller, listing, cause)
    report = diligence.report(listing["id"])
    assert report["risk"] == "high"
    assert any("loss limit" in flag for flag in report["red_flags"])


def test_pitch_claims_are_flagged_deterministically(price_box):
    seller = make_seller()
    listing = make_listing(seller, pitch="Guaranteed profits, risk-free!")
    for _ in range(4):
        finished_run(seller, listing)
    report = diligence.report(listing["id"])
    assert report["risk"] != "low"
    assert sum("unsupported claim" in flag for flag in report["red_flags"]) == 2


def test_report_is_cached_until_the_record_changes(price_box, monkeypatch):
    seller = make_seller()
    listing = make_listing(seller)
    calls = []
    monkeypatch.setattr(analyst, "ask", lambda prompt: calls.append(prompt))
    first = diligence.report(listing["id"])
    assert diligence.report(listing["id"]) is first and len(calls) == 1
    finished_run(seller, listing)
    assert diligence.report(listing["id"]) is not first and len(calls) == 2


def test_cache_expires_with_time(monkeypatch):
    listing = make_listing()
    first = diligence.report(listing["id"])
    stamp, key, built = diligence._cache[listing["id"]]
    diligence._cache[listing["id"]] = (stamp - diligence.CACHE_SECONDS - 1, key, built)
    assert diligence.report(listing["id"]) is not first


def test_valid_ai_answer_is_used_and_credited(price_box, monkeypatch):
    seller = make_seller()
    listing = make_listing(seller)
    for _ in range(4):
        finished_run(seller, listing)
    monkeypatch.setattr(analyst, "ask", lambda prompt: ai_answer())
    report = diligence.report(listing["id"])
    assert report["by"] == analyst.brain_name() and report["headline"].startswith("Solid record")
    assert report["facts"]["survived"] == 4


def test_ai_prompt_contains_only_facts_and_pitch(price_box, monkeypatch):
    seller = make_seller()
    listing = make_listing(seller, pitch="Plain pitch")
    seen = []
    monkeypatch.setattr(analyst, "ask", lambda prompt: seen.append(prompt))
    diligence.report(listing["id"])
    assert "Plain pitch" in seen[0] and "ada@example.com" not in seen[0] and seller["id"] not in seen[0]


@pytest.mark.parametrize("answer", [
    None, {}, ai_answer(risk="great"), ai_answer(headline=""), ai_answer(headline="x" * 500),
    ai_answer(findings=["only one"]), ai_answer(findings="not a list"), ai_answer(findings=[1, 2, 3]),
    ai_answer(red_flags="nope"), ai_answer(findings=["Return was +37.00%.", "b", "c"]),
    ai_answer(headline="You will make 9999 dollars"),
])
def test_invalid_or_inventive_ai_answers_fall_back(price_box, monkeypatch, answer):
    seller = make_seller()
    listing = make_listing(seller)
    for _ in range(4):
        finished_run(seller, listing)
    monkeypatch.setattr(analyst, "ask", lambda prompt: answer)
    assert diligence.report(listing["id"])["by"] == "rules"


def test_ai_cannot_lower_the_deterministic_risk_or_hide_pitch_claims(price_box, monkeypatch):
    seller = make_seller()
    listing = make_listing(seller, pitch="This bot is guaranteed to win")
    for _ in range(4):
        finished_run(seller, listing)
    monkeypatch.setattr(analyst, "ask", lambda prompt: ai_answer(risk="low"))
    report = diligence.report(listing["id"])
    assert report["by"] == analyst.brain_name() and report["risk"] != "low"
    assert any("guarantee" in flag for flag in report["red_flags"])


def test_failing_analyst_never_breaks_the_report(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "key")
    monkeypatch.setenv("AI_ANALYST_BRAIN", "gemini:test")
    from parable.config import get_settings
    get_settings.cache_clear()

    def boom(brain, prompt):
        raise RuntimeError("network down")

    monkeypatch.setattr("parable.minds.chat_json", boom)
    assert diligence.report(make_listing()["id"])["by"] == "rules"


def test_inventive_answer_gets_one_corrective_retry(price_box, monkeypatch):
    seller = make_seller()
    listing = make_listing(seller)
    for _ in range(4):
        finished_run(seller, listing)
    prompts = []
    answers = [ai_answer(headline="Solid record with 97 of 4 runs surviving."), ai_answer()]
    monkeypatch.setattr(analyst, "ask", lambda prompt: prompts.append(prompt) or answers[len(prompts) - 1])
    report = diligence.report(listing["id"])
    assert len(prompts) == 2 and "97" in prompts[1] and "rejected" in prompts[1]
    assert report["by"] == analyst.brain_name()


def test_second_inventive_answer_still_falls_back(price_box, monkeypatch):
    seller = make_seller()
    listing = make_listing(seller)
    finished_run(seller, listing)
    monkeypatch.setattr(analyst, "ask", lambda prompt: ai_answer(headline="Made up 12345 numbers."))
    assert diligence.report(listing["id"])["by"] == "rules"
