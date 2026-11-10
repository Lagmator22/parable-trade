import pytest

from parable.errors import LabError
from parable.lab import compiler, llm
from parable.lab.consts import MAX_STEPS_CHARS
from parable.lab.formula import FORMULA_REFERENCE
from parable.lab.llm import AiAuth
from parable.lab.spec import parse_spec
from parable.lab.templates import TEMPLATES, template_spec

GOOD = {
    "name": "EMA cross", "summary": "Follows momentum.",
    "params": {"fast": {"value": 12, "min": 5, "max": 30, "step": 1}, "slow": {"value": 26, "min": 20, "max": 60, "step": 2}},
    "entry": "cross_above(ema(close, fast), ema(close, slow))",
    "exit": "cross_below(ema(close, fast), ema(close, slow))", "stop_loss_pct": 3,
    "built_by": "jev:liar", "symbol": "evil:SYM", "interval": "1d",
}
BAD = {**GOOD, "entry": "close.real > 3"}
OWN = AiAuth(provider="openai", model="gpt-x", key="sk-compiler-secret-key")
PLATFORM = AiAuth(provider="platform", model="gemini:gemini-3.5-flash-lite")


class Script:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.prompts = []
        self.systems = []

    def __call__(self, auth, prompt, *, system=None, timeout=45):
        self.prompts.append(prompt)
        self.systems.append(system)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


@pytest.fixture
def script(monkeypatch):
    def install(*replies):
        fake = Script(*replies)
        monkeypatch.setattr(llm, "chat_json", fake)
        return fake

    return install


def test_describe_spec_chips():
    spec = parse_spec({**GOOD, "symbol": "fake:X", "built_by": "manual", "take_profit_pct": 12.5, "trailing_stop_pct": 4})
    chips = compiler.describe_spec(spec)
    assert [(c.kind, c.text) for c in chips] == [
        ("entry", "Buy when EMA(12) crosses above EMA(26)"),
        ("exit", "Sell when EMA(12) crosses below EMA(26)"),
        ("risk", "Stop loss 3%"), ("risk", "Take profit 12.5%"), ("risk", "Trailing stop 4%"),
        ("size", "Use 100% of cash"), ("risk", "Fees 0.10% + 0.05% slippage per side")]


def test_describe_spec_without_exit_or_stops_and_every_template():
    spec = parse_spec({"symbol": "fake:X", "interval": "1h", "entry": "close > sma(close, 20) and rsi(close, 14) < 70"})
    texts = [c.text for c in compiler.describe_spec(spec)]
    assert texts[0] == "Buy when price is above SMA(20) and RSI(14) is below 70"
    assert not any(t.startswith(("Sell", "Stop")) for t in texts)
    for template_id in TEMPLATES:
        chips = compiler.describe_spec(template_spec(template_id, "fake:X", "1h"))
        assert chips[0].text.startswith("Buy when") and "?" not in "".join(c.text for c in chips)


def test_compile_valid_forces_server_fields(script):
    fake = script(GOOD)
    base = parse_spec({**GOOD, "symbol": "fake:BASE", "interval": "1h", "name": "Base one"})
    result = compiler.compile_steps("buy when the fast EMA crosses the slow one", "fake:BTCUSDT", "1h", OWN, base=base)
    assert isinstance(result, compiler.CompileResult) and result.attempts == 1
    assert result.spec.symbol == "fake:BTCUSDT" and result.spec.interval == "1h"
    assert result.built_by == result.spec.built_by == "openai:gpt-x"
    assert result.summary == "Follows momentum." and result.rules[0].text == "Buy when EMA(12) crosses above EMA(26)"
    assert len(fake.prompts) == 1 and fake.systems[0]
    prompt = fake.prompts[0]
    assert FORMULA_REFERENCE in prompt and "buy when the fast EMA crosses the slow one" in prompt
    assert all(t in prompt for t in TEMPLATES) and "Base one" in prompt and "fake:BTCUSDT" in prompt
    assert "stop_loss_pct" in prompt and OWN.key not in prompt


def test_built_by_for_platform_models(script):
    script(GOOD)
    assert compiler.compile_steps("go", "fake:X", "1h", PLATFORM).built_by == "gemini:gemini-3.5-flash-lite"
    assert compiler.built_by_for(AiAuth(provider="anthropic", model="claude-x", key="k")) == "anthropic:claude-x"


def test_long_name_and_summary_are_trimmed(script):
    script({**GOOD, "name": "n" * 200, "summary": "s" * 900})
    result = compiler.compile_steps("go", "fake:X", "1h", OWN)
    assert len(result.spec.name) == 60 and len(result.spec.summary) == 300


def test_invalid_then_fixed_includes_error_text(script):
    fake = script(BAD, GOOD)
    result = compiler.compile_steps("go", "fake:X", "1h", OWN)
    assert result.attempts == 2 and len(fake.prompts) == 2
    retry = fake.prompts[1]
    assert "rejected" in retry and "close.real" in retry and "entry" in retry.split("Problems:")[1]


def test_invalid_twice_is_bad_output(script):
    fake = script(BAD, BAD)
    with pytest.raises(LabError) as err:
        compiler.compile_steps("go", "fake:X", "1h", OWN)
    assert err.value.status == 502 and err.value.code == "bad_output" and len(fake.prompts) == 2
    assert OWN.key not in err.value.detail


def test_non_json_reply_gets_one_retry(script):
    fake = script(LabError(502, "bad_output", "the model did not return JSON"), GOOD)
    assert compiler.compile_steps("go", "fake:X", "1h", OWN).attempts == 2
    assert "did not return JSON" in fake.prompts[1]
    script(["not an object"], GOOD)
    assert compiler.compile_steps("go", "fake:X", "1h", OWN).attempts == 2


def test_provider_errors_are_not_retried(script):
    for code, status in (("bad_key", 401), ("rate_limited", 429), ("model_unavailable", 503)):
        fake = script(LabError(status, code, "nope"))
        with pytest.raises(LabError) as err:
            compiler.compile_steps("go", "fake:X", "1h", OWN)
        assert err.value.code == code and len(fake.prompts) == 1


def test_steps_validation(script):
    fake = script(GOOD)
    for steps, status in (("", 400), ("   ", 400), ("x" * (MAX_STEPS_CHARS + 1), 413)):
        with pytest.raises(LabError) as err:
            compiler.compile_steps(steps, "fake:X", "1h", OWN)
        assert err.value.status == status
    assert fake.prompts == []
    compiler.compile_steps("x" * MAX_STEPS_CHARS, "fake:X", "1h", OWN)


def test_question_ids_are_stable():
    found = compiler.questions()
    assert [q.id for q in found] == ["family", "speed", "risk", "size"]
    assert [o.id for o in found[0].options] == ["trend", "dip", "mean_revert", "breakout", "rsi", "macd", "bollinger"]
    assert [o.id for o in found[1].options] == ["fast", "medium", "slow"]
    assert [o.id for o in found[2].options] == ["tight", "normal", "wide"]
    assert [o.id for o in found[3].options] == ["small", "half", "full"]
    assert all(o.label for q in found for o in q.options)


def test_build_from_answers_scaling_and_risk():
    medium = compiler.build_from_answers({"family": "trend"}, "fake:X", "1h")
    assert medium.built_by == "questionnaire" == medium.spec.built_by and medium.attempts == 1
    assert {k: p.value for k, p in medium.spec.params.items()} == {"fast": 10, "slow": 40}
    assert medium.spec.stop_loss_pct == 5 and medium.spec.size_pct == 100 and medium.spec.trailing_stop_pct == 0
    fast = compiler.build_from_answers({"family": "trend", "speed": "fast", "risk": "tight", "size": "small"}, "fake:X", "1h")
    assert {k: p.value for k, p in fast.spec.params.items()} == {"fast": 5, "slow": 30}
    assert fast.spec.stop_loss_pct == 2 and fast.spec.size_pct == 25
    slow = compiler.build_from_answers({"family": "trend", "speed": "slow", "risk": "wide", "size": "half"}, "fake:X", "1h")
    assert {k: p.value for k, p in slow.spec.params.items()} == {"fast": 20, "slow": 80}
    assert slow.spec.stop_loss_pct == 10 and slow.spec.size_pct == 50


def test_non_period_params_are_not_scaled():
    result = compiler.build_from_answers({"family": "dip", "speed": "slow"}, "fake:X", "1h")
    assert result.spec.params["look"].value == 40 and result.spec.params["drop"].value == 5


def test_every_family_and_speed_builds_a_valid_spec():
    for family in TEMPLATES:
        for speed in ("fast", "medium", "slow"):
            result = compiler.build_from_answers({"family": family, "speed": speed}, "fake:X", "1d")
            parse_spec(result.spec.model_dump())
            for p in result.spec.params.values():
                assert p.min <= p.value <= p.max


def test_build_from_answers_rejects_bad_input():
    for answers in ({}, {"family": "moon"}, {"family": "trend", "speed": "warp"}):
        with pytest.raises(LabError) as err:
            compiler.build_from_answers(answers, "fake:X", "1h")
        assert err.value.status == 400
    assert compiler.build_from_answers({"family": "rsi", "bogus": "x"}, "fake:X", "1h").spec.name


def test_jev_build_asks_the_questionnaire(monkeypatch):
    seen = {}

    def fake_choices(model, situation, questions):
        seen.update(model=model, situation=situation, questions=questions)
        return {"family": "macd", "speed": "fast", "risk": "wide", "size": "half"}

    monkeypatch.setattr(llm, "chat_json", lambda *a, **k: pytest.fail("jev must not use chat_json"))
    monkeypatch.setattr(llm, "jev_choices", fake_choices)
    auth = AiAuth(provider="platform", model="jev:gemma-4-31b-it")
    for fn in (compiler.compile_steps, lambda s, sym, i, a: compiler.jev_build(s, sym, i, a)):
        result = fn("buy momentum, wide stop", "fake:X", "1h", auth)
        assert result.built_by == "jev:gemma-4-31b-it" == result.spec.built_by
        assert result.spec.stop_loss_pct == 10 and result.spec.size_pct == 50 and result.spec.params["fast"].value == 8
    assert seen["model"] == "gemma-4-31b-it" and "buy momentum, wide stop" in seen["situation"]
    assert set(seen["questions"]) == {"family", "speed", "risk", "size"}
    assert seen["questions"]["speed"]["options"] == ["fast", "medium", "slow"]
    with pytest.raises(LabError):
        compiler.compile_steps("", "fake:X", "1h", auth)


def test_ideas_skip_invalid_variants(script):
    base = parse_spec({**GOOD, "symbol": "fake:X", "interval": "1h"})
    other = {**GOOD, "name": "Second", "stop_loss_pct": 6}
    fake = script({"variants": [GOOD, BAD, other, "junk"]})
    found = compiler.ideas(base, "make it safer", OWN, n=3)
    assert [r.spec.name for r in found] == ["EMA cross", "Second"]
    assert all(r.built_by == "openai:gpt-x" and r.spec.symbol == "fake:X" for r in found)
    assert "3 different specs" in fake.prompts[0] and "make it safer" in fake.prompts[0]


def test_ideas_failures_and_limits(script):
    base = parse_spec({**GOOD, "symbol": "fake:X", "interval": "1h"})
    for reply in ({"variants": [BAD]}, {"variants": "no"}, {}):
        script(reply)
        with pytest.raises(LabError) as err:
            compiler.ideas(base, "x", OWN)
        assert err.value.code == "bad_output"
    script({"variants": [GOOD] * 9})
    assert len(compiler.ideas(base, "x", OWN, n=99)) == 5
    with pytest.raises(LabError) as err:
        compiler.ideas(base, "x", AiAuth(provider="platform", model="jev:a"))
    assert err.value.status == 400
