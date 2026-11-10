import threading

import pytest

from parable import bot_runner, jev, ledger, minds, prices, referee
from parable.config import get_settings
from parable.models import PRESETS, BotRules, TradeDecision, fingerprint

USD = 1_000_000
PRICE = 3000 * 10**8


def state(history, cash=1000 * USD, eth_wei=0, strategy="momentum", max_trade=250 * USD) -> dict:
    return {
        "strategy": strategy, "history": [int(p * 10**8) for p in history], "price": PRICE,
        "cash_usd": cash, "eth_wei": eth_wei, "equity_usd": cash, "max_trade_usd": max_trade,
        "max_loss_bps": 300,
    }


ETH_WORTH_500 = 500 * USD * 10**20 // PRICE


def test_momentum_rule():
    assert bot_runner.rule_decide(state([3000, 3010])).action == "buy"
    assert bot_runner.rule_decide(state([3010, 3000])).action == "sell"
    assert bot_runner.rule_decide(state([3000, 3000])).action == "hold"
    assert bot_runner.rule_decide(state([3000])).action == "hold"


def test_dip_buyer_rule():
    assert bot_runner.rule_decide(state([3100, 3090, 3050], strategy="dip_buyer")).action == "buy"
    held = state([3000, 3050, 3100], strategy="dip_buyer", eth_wei=ETH_WORTH_500)
    assert bot_runner.rule_decide(held).action == "sell"
    assert bot_runner.rule_decide(state([3000, 3050, 3100], strategy="dip_buyer")).action == "hold"
    assert bot_runner.rule_decide(state([3100, 3099], strategy="dip_buyer")).action == "hold"


def test_mean_revert_rule():
    spike = state([3000, 3000, 3000, 3000, 3060], strategy="mean_revert", eth_wei=ETH_WORTH_500)
    assert bot_runner.rule_decide(spike).action == "sell"
    drop = state([3000, 3000, 3000, 3000, 2940], strategy="mean_revert")
    assert bot_runner.rule_decide(drop).action == "buy"
    assert bot_runner.rule_decide(state([3000, 3001, 3000, 2999], strategy="mean_revert")).action == "hold"
    assert bot_runner.rule_decide(state([3000], strategy="mean_revert")).action == "hold"


def test_yolo_rule_alternates_between_cash_and_eth():
    assert bot_runner.rule_decide(state([3000], strategy="yolo")).action == "buy"
    assert bot_runner.rule_decide(state([3000], strategy="yolo", cash=0, eth_wei=ETH_WORTH_500)).action == "sell"
    assert bot_runner.rule_decide(state([], strategy="yolo")).amount_usd == 250 * USD


def test_unknown_strategy_uses_momentum():
    assert bot_runner.rule_decide(state([3000, 3010], strategy="mystery")).action == "buy"


def test_clamp_limits_to_cap_and_holdings():
    big = TradeDecision(action="buy", amount_usd=900 * USD, reason="x")
    assert bot_runner.clamp(big, state([3000])).amount_usd == 250 * USD
    assert bot_runner.clamp(big, state([3000], cash=40 * USD)).amount_usd == 40 * USD
    sell = TradeDecision(action="sell", amount_usd=900 * USD, reason="x")
    assert bot_runner.clamp(sell, state([3000], eth_wei=ETH_WORTH_500)).amount_usd == 250 * USD


def test_clamp_turns_empty_trade_into_hold():
    sell = TradeDecision(action="sell", amount_usd=10 * USD, reason="x")
    clamped = bot_runner.clamp(sell, state([3000]))
    assert clamped.action == "hold" and "nothing to trade" in clamped.reason
    hold = TradeDecision(action="hold", reason="wait")
    assert bot_runner.clamp(hold, state([3000])) == hold


def test_decide_rule_brain_has_no_fallback_tag():
    decision = bot_runner.decide(state([3000, 3010]), "rule")
    assert decision.action == "buy" and not decision.reason.startswith(bot_runner.FALLBACK_TAG)


def test_decide_unconfigured_brain_falls_back_to_rule():
    decision = bot_runner.decide(state([3000, 3010]), "claude:nothing")
    assert decision.action == "buy"
    assert decision.reason.startswith(bot_runner.FALLBACK_TAG)


def test_decide_failing_ai_brain_falls_back(monkeypatch):
    def broken(_state):
        raise RuntimeError("model down")

    monkeypatch.setattr(bot_runner, "build_brains", lambda: {"gemini:x": {"decide": broken, "ready": True}})
    decision = bot_runner.decide(state([3010, 3000]), "gemini:x")
    assert decision.action == "hold" or decision.reason.startswith(bot_runner.FALLBACK_TAG)
    assert decision.reason.startswith(bot_runner.FALLBACK_TAG)


def test_decide_uses_ready_ai_brain_and_clamps(monkeypatch):
    ai = TradeDecision(action="buy", amount_usd=999 * USD, reason="ai says buy")
    monkeypatch.setattr(bot_runner, "build_brains", lambda: {"gemini:x": {"decide": lambda s: ai, "ready": True}})
    decision = bot_runner.decide(state([3000]), "gemini:x")
    assert decision.reason == "ai says buy" and decision.amount_usd == 250 * USD


def test_available_brains_reflects_settings(monkeypatch):
    baseline = bot_runner.available_brains()
    assert baseline["rule"] is True and not any(v for k, v in baseline.items() if k != "rule")
    monkeypatch.setenv("CLAUDE_MODELS", "claude-a")
    monkeypatch.setenv("JEV_MODELS", "jev-a")
    monkeypatch.setenv("GEMINI_MODELS", "gem-a")
    monkeypatch.setenv("GEMMA_MODELS", "gem-b")
    get_settings.cache_clear()
    brains = bot_runner.available_brains()
    assert set(brains) == {"rule", "claude:claude-a", "jev:jev-a", "gemini:gem-a", "gemma:gem-b"}
    assert brains["rule"] is True and not any(v for k, v in brains.items() if k != "rule")
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    get_settings.cache_clear()
    brains = bot_runner.available_brains()
    assert brains["gemini:gem-a"] and brains["gemma:gem-b"] and not brains["claude:claude-a"]


def test_to_decision_converts_dollars_to_micro_usd():
    decision = bot_runner.to_decision({"action": "buy", "amount_dollars": 20.5, "reason": "r"})
    assert decision.amount_usd == 20_500_000
    with pytest.raises(Exception):
        bot_runner.to_decision({"action": "buy", "amount_dollars": -1, "reason": "r"})
    with pytest.raises(Exception):
        bot_runner.to_decision({"action": "moon", "amount_dollars": 1, "reason": "r"})
    with pytest.raises(Exception):
        bot_runner.to_decision({"action": "buy", "amount_dollars": float("nan"), "reason": "r"})


def test_extract_json_handles_fences_thoughts_and_picks_last():
    text = '<thought>{"action": "sell"}</thought>```json\n{"action": "hold", "reason": "a"}\n```{"action": "buy"}'
    assert minds.extract_json(text, "action") == {"action": "buy"}
    assert bot_runner.extract_json('noise {"risk": "low"} tail') == {"risk": "low"}
    with pytest.raises(ValueError):
        minds.extract_json('{"risk": "low"}', "action")
    with pytest.raises(ValueError):
        minds.extract_json("no json here")


def test_chat_json_rejects_non_ai_brains():
    with pytest.raises(ValueError):
        minds.chat_json("rule", "hi")


def test_chat_json_google_brain(monkeypatch):
    class Reply:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": '```json\n{"risk": "low"}\n```'}}]}

    seen = {}

    def fake_post(url, **kwargs):
        seen["url"], seen["body"] = url, kwargs["json"]
        return Reply()

    monkeypatch.setattr(minds.httpx, "post", fake_post)
    assert minds.chat_json("gemini:flash", "prompt") == {"risk": "low"}
    assert seen["url"].endswith("/chat/completions") and seen["body"]["model"] == "flash"


def test_claude_credit_error_pauses_claude(monkeypatch):
    monkeypatch.setattr(minds, "_claude_off_until", 0.0)
    assert minds.claude_usable()
    minds.note_claude_error(RuntimeError("Your credit balance is too low"))
    assert not minds.claude_usable()
    monkeypatch.setattr(minds, "_claude_off_until", 0.0)
    minds.note_claude_error(RuntimeError("timeout"))
    assert minds.claude_usable()


def test_probe_claude_without_key_does_nothing():
    minds.probe_claude()
    assert minds.claude_usable()


def test_jev_to_decision_sizes_by_confidence():
    answer = {"choice": "buy", "probabilities": {"buy": 0.8, "hold": 0.15, "sell": 0.05}}
    decision = jev.to_decision(answer, 250 * USD)
    assert decision.action == "buy" and decision.amount_usd == 200 * USD
    assert "buy 80%" in decision.reason
    assert jev.to_decision({"choice": "hold", "probabilities": {}}, 250 * USD).amount_usd == 0
    assert jev.to_decision({"choice": "sell", "probabilities": {"sell": 0.0}}, 250 * USD).amount_usd == jev.MIN_TRADE_USD
    with pytest.raises(ValueError):
        jev.to_decision({"choice": "moon"}, 250 * USD)


def test_jev_question_embeds_the_situation():
    body = jev.jev_question(state([3000, 3010]))
    text = body["state"][0]["content"][0]["text"]
    assert "momentum" in text and "Call decide_trade" not in text
    assert set(body["questions"]["action"]["criteria"]) == {"buy", "sell", "hold"}


def test_fingerprint_depends_on_brain_strategy_and_limits():
    base = BotRules(strategy="momentum")
    assert fingerprint(base) == fingerprint(BotRules(strategy="momentum"))
    assert fingerprint(base).startswith("0x") and len(fingerprint(base)) == 18
    assert fingerprint(base) != fingerprint(BotRules(strategy="dip_buyer"))
    assert fingerprint(base) != fingerprint(BotRules(strategy="momentum", brain="gemini:x"))
    assert fingerprint(base) != fingerprint(BotRules(strategy="momentum", max_loss_bps=100))
    assert fingerprint(base) != fingerprint(BotRules(strategy="momentum", max_trade_usd=1))
    assert fingerprint(base) == fingerprint(BotRules(strategy="momentum", lease_seconds=5, start_cash_usd=7))


def test_presets_cover_all_strategies():
    assert set(PRESETS) == {"momentum", "dip_buyer", "mean_revert", "yolo"}
    assert BotRules(strategy="yolo").start_cash_usd == 1000 * USD


@pytest.mark.parametrize("field", ["start_cash_usd", "max_trade_usd", "max_loss_bps", "lease_seconds"])
def test_rules_reject_non_positive_limits(field):
    with pytest.raises(Exception):
        BotRules(strategy="momentum", **{field: 0})


def test_observe_keeps_a_sliding_window():
    samples = []
    for step in range(30):
        history = bot_runner.observe(samples, step)
    assert len(history) == bot_runner.HISTORY_WINDOW and history[-1] == 29


def test_run_bot_trades_against_referee(wait_until):
    ticks = {"n": 0}

    def wobble():
        ticks["n"] += 1
        return int((3000 + (ticks["n"] % 4) * 5) * 10**8)

    prices.set_price_source(wobble)
    rules = BotRules(strategy="yolo", max_trade_usd=100 * USD, max_loss_bps=5000, lease_seconds=60)
    run = referee.open_run("s_a", rules, "practice", "loop")
    stop = threading.Event()
    worker = threading.Thread(target=bot_runner.run_bot, args=(run["id"], rules, stop, 0.001), daemon=True)
    worker.start()
    assert wait_until(lambda: referee.get_run(run["id"])["trades"] >= 3)
    stop.set()
    worker.join(timeout=3)
    assert not worker.is_alive()
    assert referee.get_run(run["id"])["trades"] >= 3
    assert len(ledger.entries(subject=f"run:{run['id']}", kind="run.trade")) >= 3


def test_run_bot_exits_when_run_is_dead(price_box):
    rules = BotRules(strategy="momentum")
    run = referee.open_run("s_a", rules, "practice", "dead")
    referee.stop(run["id"])
    worker = threading.Thread(target=bot_runner.run_bot, args=(run["id"], rules, threading.Event(), 0.001))
    worker.start()
    worker.join(timeout=3)
    assert not worker.is_alive()


def test_run_bot_exits_on_missing_run(price_box):
    worker = threading.Thread(target=bot_runner.run_bot, args=(999, BotRules(strategy="momentum"),
                                                              threading.Event(), 0.001))
    worker.start()
    worker.join(timeout=3)
    assert not worker.is_alive()


def test_run_bot_stops_itself_on_loss_limit(price_box, monkeypatch):
    rules = BotRules(strategy="yolo", max_trade_usd=1000 * USD, max_loss_bps=300, lease_seconds=60)
    run = referee.open_run("s_a", rules, "practice", "crash")
    stop = threading.Event()
    worker = threading.Thread(target=bot_runner.run_bot, args=(run["id"], rules, stop, 0.001), daemon=True)
    original_trade = referee.trade

    def crash_after_buy(*args):
        result = original_trade(*args)
        price_box.set(2000)
        return result

    monkeypatch.setattr(referee, "trade", crash_after_buy)
    worker.start()
    worker.join(timeout=5)
    assert not worker.is_alive()
    assert referee.get_run(run["id"])["cause"] == "loss_limit"


def test_run_bot_survives_brain_crash_and_keeps_going(price_box, monkeypatch, wait_until):
    calls = {"n": 0}

    def flaky(state_, brain):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom https://secret.example/key?abc")
        return TradeDecision(action="buy", amount_usd=USD, reason="ok")

    monkeypatch.setattr(bot_runner, "decide", flaky)
    rules = BotRules(strategy="momentum", lease_seconds=60)
    run = referee.open_run("s_a", rules, "practice", "flaky")
    stop = threading.Event()
    worker = threading.Thread(target=bot_runner.run_bot, args=(run["id"], rules, stop, 0.001), daemon=True)
    worker.start()
    assert wait_until(lambda: referee.get_run(run["id"])["trades"] >= 1)
    stop.set()
    worker.join(timeout=3)
    assert calls["n"] >= 2


def test_redact_removes_urls():
    cleaned = bot_runner.redact(RuntimeError("failed https://api.example.com/x?key=SECRET now"))
    assert "SECRET" not in cleaned and "<url>" in cleaned
