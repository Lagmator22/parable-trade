import logging
import threading
import time

import pytest

from parable import bot_agent, ledger, minds, referee
from parable.lab import markets
from run_support import FakeSpec, agent_rules, agent_run, feed, install_fake_lab

USD = 1_000_000
PRICE = 3000 * 10**8


def test_extract_json_handles_fences_thoughts_and_picks_last():
    text = '<thought>{"action": "sell"}</thought>```json\n{"action": "hold", "reason": "a"}\n```{"action": "buy"}'
    assert minds.extract_json(text, "action") == {"action": "buy"}
    assert minds.extract_json('noise {"risk": "low"} tail') == {"risk": "low"}
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


def test_redact_removes_urls():
    cleaned = bot_agent.redact(RuntimeError("failed https://api.example.com/x?key=SECRET now"))
    assert "SECRET" not in cleaned and "<url>" in cleaned


BASE = int(time.time()) // 3600 * 3600 - 3600 * 20


def bar(n: int, close: float = 3000.0) -> list[float]:
    return [BASE + 3600 * n, close, close + 1, close - 1, close, 10.0]


class Harness:
    def __init__(self, feed, signals, run) -> None:
        self.feed, self.signals, self.run = feed, signals, run
        self.rules = agent_rules()
        self.state = {"entry_t": 0.0}
        self.spec = FakeSpec()

    def tick(self, bars: list[list[float]]) -> None:
        self.feed.bars = bars
        markets.clear_cache()
        assert bot_agent.tick(self.run["id"], self.rules, self.spec, self.state)

    def row(self) -> dict:
        return referee.load(self.run["id"])


@pytest.fixture
def harness(feed, monkeypatch, price_box):
    signals = install_fake_lab(monkeypatch)
    return Harness(feed, signals, agent_run())


def test_agent_buys_once_per_new_closed_bar(harness):
    harness.signals.script = ["buy", "buy", "buy"]
    harness.tick([bar(0), bar(1)])
    first = harness.row()
    assert first["trades"] == 1 and first["last_bar_t"] == BASE + 3600
    expected_cash = 1000 * USD * 50_00 // 10_000
    assert first["units"] > 0 and 1000 * USD - first["cash_usd"] <= expected_cash + expected_cash // 1000 + 1
    harness.tick([bar(0), bar(1)])
    harness.tick([bar(0), bar(1)])
    assert harness.signals.decisions == 1 and harness.row()["trades"] == 1
    harness.tick([bar(0), bar(1), bar(2)])
    assert harness.signals.decisions == 2 and harness.row()["trades"] == 1


def test_agent_sells_everything_on_sell_signal(harness):
    harness.signals.script = ["buy", "sell"]
    harness.tick([bar(0)])
    held = harness.row()["units"]
    assert held > 0
    harness.tick([bar(0), bar(1)])
    flat = harness.row()
    assert flat["units"] == 0 and flat["entry_price"] == 0 and flat["trades"] == 2
    assert flat["cash_usd"] < 1000 * USD


def test_sell_while_flat_and_buy_while_long_do_nothing(harness):
    harness.signals.script = ["sell", "buy", "buy"]
    harness.tick([bar(0)])
    assert harness.row()["trades"] == 0
    harness.tick([bar(0), bar(1)])
    harness.tick([bar(0), bar(1), bar(2)])
    assert harness.row()["trades"] == 1


def test_open_bar_is_never_used(harness):
    harness.signals.script = ["buy"]
    live = [BASE + 3600 * 19 + 3590, 3000.0, 3001.0, 2999.0, 3000.0, 1.0]
    harness.tick([live])
    assert harness.signals.decisions == 0 and harness.row()["trades"] == 0
    assert harness.row()["last_bar_t"] == 0


def test_stop_reason_sells_on_the_tick_price(harness, price_box):
    harness.signals.script = ["buy"]
    harness.tick([bar(0)])
    price_box.set(2900)
    harness.signals.stop = ("stop", 2900.0)
    harness.tick([bar(0)])
    row = harness.row()
    assert row["units"] == 0 and row["trades"] == 2
    reasons = [e["data"]["reason"] for e in ledger.entries(subject=f"run:{row['id']}") if e["kind"] == "run.trade"]
    assert reasons[0] == "stop"


def test_high_water_follows_price_while_long(harness, price_box):
    harness.signals.script = ["buy"]
    harness.tick([bar(0)])
    price_box.set(3300)
    harness.tick([bar(0)])
    assert harness.row()["high_water"] == 3300 * 10**8
    price_box.set(3100)
    harness.tick([bar(0)])
    assert harness.row()["high_water"] == 3300 * 10**8


def test_every_tick_records_a_point(harness):
    harness.tick([bar(0)])
    harness.tick([bar(0)])
    assert len(referee.points(harness.run["id"])) == 2


def test_tick_stops_when_run_is_dead(harness):
    referee.stop(harness.run["id"])
    assert bot_agent.tick(harness.run["id"], harness.rules, harness.spec, harness.state) is False


def test_run_agent_survives_data_errors_and_redacts(harness, caplog):
    def broken(*args, **kwargs):
        raise RuntimeError("down at https://secret.example/path?key=abc")

    harness.feed.candles = broken
    stop = threading.Event()
    worker = threading.Thread(target=bot_agent.run_agent, args=(harness.run["id"], stop, 0.005))
    with caplog.at_level(logging.WARNING, logger="parable.bot"):
        worker.start()
        deadline = time.time() + 3
        while time.time() < deadline and len(referee.points(harness.run["id"])) < 3:
            time.sleep(0.01)
        stop.set()
        worker.join(3)
    assert len(referee.points(harness.run["id"])) >= 3 and not worker.is_alive()
    assert "secret.example" not in caplog.text and "<url>" in caplog.text
    assert harness.row()["trades"] == 0


def test_run_agent_exits_when_run_ends(harness):
    referee.stop(harness.run["id"])
    worker = threading.Thread(target=bot_agent.run_agent, args=(harness.run["id"], threading.Event(), 0.005))
    worker.start()
    worker.join(3)
    assert not worker.is_alive()


def test_run_agent_loads_spec_by_version_id(harness, monkeypatch):
    import parable.lab.spec as fake_spec
    seen = []
    monkeypatch.setattr(fake_spec, "load_spec", lambda version_id: seen.append(version_id) or FakeSpec())
    referee.stop(harness.run["id"])
    bot_agent.run_agent(harness.run["id"], threading.Event(), 0.005)
    assert seen == ["v_test000001"]


def real_agent(entry: str, stop_loss_pct: float = 0, exit_rule: str = ""):
    from parable.db import execute
    from parable.lab.spec import parse_spec

    spec = parse_spec({"name": "Real", "symbol": "fake:BTCUSDT", "interval": "1h", "entry": entry,
                       "exit": exit_rule, "size_pct": 50, "stop_loss_pct": stop_loss_pct, "fee_bps": 10,
                       "slippage_bps": 5})
    column = "spec_" + "json"
    execute(f"INSERT INTO agent_versions (id, agent_id, n, name, {column}, spec_hash) VALUES (?,?,?,?,?,?)",
            ("v_test000001", "a_x", 1, "Real", spec.model_dump_json(), "ab" * 32))
    return spec


def test_real_spec_and_signals_drive_the_bot(feed, price_box):
    from parable.lab.spec import load_spec

    spec = real_agent("close > 0", stop_loss_pct=5)
    run = agent_run()
    state = {"entry_t": 0.0}
    feed.bars = [bar(n) for n in range(300)]
    markets.clear_cache()
    assert bot_agent.tick(run["id"], agent_rules(), load_spec("v_test000001"), state)
    row = referee.load(run["id"])
    assert row["trades"] == 1 and row["units"] > 0 and spec.size_pct == 50
    price_box.set(2800)
    markets.clear_cache()
    assert bot_agent.tick(run["id"], agent_rules(), load_spec("v_test000001"), state)
    assert referee.load(run["id"])["units"] == 0
