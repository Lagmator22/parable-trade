import pytest

from market_support import make_listing, make_seller, set_headline
from parable import analyst, diligence, proofs, referee
from parable.db import execute
from parable.errors import LabError

STRONG = {"total_return_pct": 40.0, "benchmark_return_pct": 10.0, "excess_return_pct": 30.0,
          "max_drawdown_pct": 10.0, "trades": 30, "sharpe": 1.5, "win_rate_pct": 55.0, "exposure_pct": 40.0}


def strong_listing(**overrides) -> dict:
    listing = make_listing(**overrides)
    set_headline(listing, **STRONG)
    execute("UPDATE proofs SET end_t = start_t + 100 * 86400 WHERE id = ?", (listing["proof_id"],))
    return listing


def ai_answer(**overrides) -> dict:
    base = {"risk": "low", "headline": "Proof returned 40.0% against 10.0% for buy and hold.",
            "findings": ["The worst drawdown was 10.0%.", "The proof holds 30 trades.", "The price is 20.0 dollars."],
            "red_flags": []}
    return {**base, **overrides}


def test_unknown_listing_is_a_404():
    with pytest.raises(LabError) as missing:
        diligence.report("l_nothing")
    assert missing.value.status == 404


def test_facts_come_from_the_proof_and_never_the_spec(manager):
    report = diligence.report(strong_listing()["id"])
    facts = report["facts"]
    assert facts["total_return_pct"] == 40.0 and facts["excess_return_pct"] == 30.0 and facts["trades"] == 30
    assert facts["span_days"] == 100.0 and facts["mode"] == "hold" and facts["allow_test_drive"] is True
    assert facts["reruns"] == 0 and facts["track"]["runs_total"] == 1 and "seller_record" in facts
    assert "entry" not in str(report) and "buy dips" not in str(report)


def test_strong_listing_is_low_risk_without_red_flags(manager):
    proofs.rerun_listing(strong_listing()["id"], make_seller("Checker", "checker@example.com")["id"])
    listing = strong_listing(title="Second")
    report = diligence.report(listing["id"])
    assert report["risk"] == "low" and report["red_flags"] == []
    assert report["headline"].startswith("Low risk") and 3 <= len(report["findings"]) <= 5


def test_every_red_flag_is_raised_from_the_facts(manager):
    listing = make_listing()
    set_headline(listing, total_return_pct=-5.0, benchmark_return_pct=10.0, max_drawdown_pct=55.0, trades=4)
    referee.stop(listing["track_run_id"], "loss_limit")
    proofs.rerun_listing(listing["id"], make_seller("Checker", "checker@example.com")["id"])
    execute("UPDATE proofs SET matched = 0 WHERE listing_id = ? AND kind = 'rerun'", (listing["id"],))
    flags = " ".join(diligence.build_report(listing)["red_flags"])
    for phrase in ("Only 4 trades", "below simply buying", "deep drawdown of 55.0%", "only 17 days",
                   "did not reproduce", "died early"):
        assert phrase in flags


def test_sample_data_is_flagged(manager):
    listing = make_listing(symbol="sample:BTCUSDT", mode="instant")
    assert any("sample data" in flag for flag in diligence.report(listing["id"])["red_flags"])


def test_pitch_claims_are_flagged_deterministically(manager):
    listing = strong_listing(title="Claimy")
    execute("UPDATE listings SET pitch = 'Guaranteed profits, risk-free!' WHERE id = ?", (listing["id"],))
    report = diligence.report(listing["id"])
    assert report["risk"] != "low" and sum("unsupported claim" in flag for flag in report["red_flags"]) == 2


def test_report_is_cached_until_the_evidence_changes(manager, monkeypatch):
    listing = strong_listing()
    calls = []
    monkeypatch.setattr(analyst, "ask", lambda prompt: calls.append(prompt))
    first = diligence.report(listing["id"])
    assert diligence.report(listing["id"]) is first and len(calls) == 1
    proofs.rerun_listing(listing["id"], make_seller("Checker", "checker@example.com")["id"])
    assert diligence.report(listing["id"]) is not first and len(calls) == 2


def test_cache_expires_with_time(manager):
    listing = make_listing()
    first = diligence.report(listing["id"])
    stamp, key, built = diligence._cache[listing["id"]]
    diligence._cache[listing["id"]] = (stamp - diligence.CACHE_SECONDS - 1, key, built)
    assert diligence.report(listing["id"]) is not first


def test_valid_ai_answer_is_used_and_credited(manager, monkeypatch):
    listing = strong_listing()
    monkeypatch.setattr(analyst, "ask", lambda prompt: ai_answer())
    report = diligence.report(listing["id"])
    assert report["by"] == analyst.brain_name() and report["headline"].startswith("Proof returned")
    assert report["facts"]["trades"] == 30


def test_ai_prompt_contains_only_facts_and_pitch(manager, monkeypatch):
    seller = make_seller()
    listing = make_listing(seller, title="Plain Agent")
    seen = []
    monkeypatch.setattr(analyst, "ask", lambda prompt: seen.append(prompt))
    diligence.report(listing["id"])
    assert "A careful agent." in seen[0] and "ada@example.com" not in seen[0] and seller["id"] not in seen[0]
    assert "buy dips" not in seen[0] and listing["version_id"] not in seen[0]


@pytest.mark.parametrize("answer", [
    None, {}, ai_answer(risk="great"), ai_answer(headline=""), ai_answer(headline="x" * 500),
    ai_answer(findings=["only one"]), ai_answer(findings="not a list"), ai_answer(findings=[1, 2, 3]),
    ai_answer(red_flags="nope"), ai_answer(findings=["Return was +37.00%.", "b", "c"]),
    ai_answer(headline="You will make 9999 dollars"),
])
def test_invalid_or_inventive_ai_answers_fall_back(manager, monkeypatch, answer):
    listing = strong_listing()
    monkeypatch.setattr(analyst, "ask", lambda prompt: answer)
    assert diligence.report(listing["id"])["by"] == "rules"


def test_ai_cannot_lower_the_deterministic_risk_or_hide_pitch_claims(manager, monkeypatch):
    listing = strong_listing()
    execute("UPDATE listings SET pitch = 'This agent is guaranteed to win' WHERE id = ?", (listing["id"],))
    monkeypatch.setattr(analyst, "ask", lambda prompt: ai_answer(risk="low"))
    report = diligence.report(listing["id"])
    assert report["by"] == analyst.brain_name() and report["risk"] != "low"
    assert any("guarantee" in flag for flag in report["red_flags"])


def test_failing_analyst_never_breaks_the_report(manager, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "key")
    monkeypatch.setenv("AI_ANALYST_BRAIN", "gemini:test")
    from parable.config import get_settings

    get_settings.cache_clear()

    def boom(brain, prompt):
        raise RuntimeError("network down")

    monkeypatch.setattr("parable.minds.chat_json", boom)
    assert diligence.report(make_listing()["id"])["by"] == "rules"


def test_inventive_answer_gets_one_corrective_retry(manager, monkeypatch):
    listing = strong_listing()
    prompts = []
    answers = [ai_answer(headline="Proof returned 97.0% against 10.0%."), ai_answer()]
    monkeypatch.setattr(analyst, "ask", lambda prompt: prompts.append(prompt) or answers[len(prompts) - 1])
    report = diligence.report(listing["id"])
    assert len(prompts) == 2 and "97" in prompts[1] and "rejected" in prompts[1]
    assert report["by"] == analyst.brain_name()


def test_second_inventive_answer_still_falls_back(manager, monkeypatch):
    listing = strong_listing()
    monkeypatch.setattr(analyst, "ask", lambda prompt: ai_answer(headline="Made up 12345 numbers."))
    assert diligence.report(listing["id"])["by"] == "rules"
