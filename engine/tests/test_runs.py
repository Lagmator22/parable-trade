import threading

import pytest

from parable import ledger, referee, runs
from parable.db import execute
from parable.models import RunRules
from parable.errors import LabError, MarketError
from parable.runs import RunManager
from run_support import FakeSpec, agent_rules, feed, insert_version, install_fake_lab

USD = 1_000_000


def rules(**overrides) -> RunRules:
    names = {"max_trade_usd": "max_trade", "start_cash_usd": "start_cash"}
    mapped = {names.get(key, key): value for key, value in overrides.items() if key not in ("strategy", "brain")}
    base = {"version_id": "v_legacy0001", "spec_hash": "ab" * 32, "symbol": "fake:BTCUSDT", "interval": "1h",
            "quote": "USDT", "start_cash": 1000 * USD, "max_trade": 250 * USD, "max_loss_bps": 300,
            "lease_seconds": 300}
    return RunRules(**{**base, **mapped})


@pytest.fixture
def manager():
    created = RunManager(interval_s=0.005)
    runs.set_manager(created)
    return created


def test_get_manager_is_a_singleton_and_set_manager_replaces():
    first = runs.get_manager()
    assert runs.get_manager() is first
    replacement = RunManager(interval_s=0.01)
    runs.set_manager(replacement)
    assert runs.get_manager() is replacement
    assert replacement.interval_s == 0.01


def test_default_interval_comes_from_settings(monkeypatch):
    monkeypatch.setenv("BOT_INTERVAL_S", "7")
    from parable.config import get_settings
    get_settings.cache_clear()
    assert RunManager().interval_s == 7




def test_stop_ends_run_and_thread(manager, wait_until):
    run = manager.start("s_a", rules(), "practice", "stoppable")
    thread = manager.workers[run["id"]][0]
    stopped = manager.stop(run["id"])
    assert stopped["status"] == "dead" and stopped["cause"] == "stopped"
    assert wait_until(lambda: not thread.is_alive())
    trades = referee.get_run(run["id"])["trades"]
    threading.Event().wait(0.05)
    assert referee.get_run(run["id"])["trades"] == trades


def test_double_stop_is_harmless(manager):
    seen = []
    manager.add_end_listener(seen.append)
    run = manager.start("s_a", rules(), "practice", "twice")
    first = manager.stop(run["id"])
    second = manager.stop(run["id"])
    assert first["cause"] == second["cause"] == "stopped"
    assert len(seen) == 1
    assert [e["kind"] for e in ledger.entries(subject=f"run:{run['id']}")].count("run.ended") == 1


def test_stop_with_loss_limit_cause_for_failed_probation(manager):
    run = manager.start("s_a", rules(), "probation", "seller stop")
    assert manager.stop(run["id"], "loss_limit")["cause"] == "loss_limit"




def test_listener_called_when_poller_ends_run_without_threads(manager):
    seen = []
    manager.add_end_listener(seen.append)
    run = referee.open_run("s_a", rules(), "practice", "unthreaded")
    execute("UPDATE runs SET expires_at = 1 WHERE id = ?", (run["id"],))
    ended = manager.poll_once()
    assert [r["id"] for r in ended] == [run["id"]]
    assert len(seen) == 1 and seen[0]["cause"] == "expired"
    assert manager.poll_once() == []
    assert len(seen) == 1


def test_multiple_listeners_and_failing_listener(manager):
    first, second = [], []

    def explode(run):
        raise RuntimeError("listener bug")

    manager.add_end_listener(explode)
    manager.add_end_listener(first.append)
    manager.add_end_listener(second.append)
    run = manager.start("s_a", rules(), "practice", "many")
    manager.stop(run["id"])
    assert len(first) == len(second) == 1




def test_probation_runs_carry_listing_and_purchase_ids(manager):
    run = manager.start("s_a", rules(), "probation", "paid", listing_id="l_1", purchase_id="p_1")
    assert run["purpose"] == "probation" and run["listing_id"] == "l_1" and run["purchase_id"] == "p_1"
    manager.stop(run["id"])


def test_start_rejects_bad_purpose_without_creating_thread(manager):
    with pytest.raises(ValueError):
        manager.start("s_a", rules(), "demo", "bad")
    assert manager.workers == {}


def test_start_poller_ends_expired_runs_and_is_idempotent(manager, wait_until):
    seen = []
    manager.add_end_listener(seen.append)
    run = referee.open_run("s_a", rules(), "practice", "polled")
    execute("UPDATE runs SET expires_at = 1 WHERE id = ?", (run["id"],))
    manager.start_poller(every_s=0.01)
    poller = manager.poller
    manager.start_poller(every_s=0.01)
    assert manager.poller is poller
    assert wait_until(lambda: len(seen) == 1)
    manager.shutdown()
    assert not poller.is_alive()




def test_resume_ends_expired_runs_and_notifies(wait_until):
    seen = []
    before = RunManager(interval_s=0.005)
    runs.set_manager(before)
    run = before.start("s_a", rules(), "probation", "overdue", purchase_id="p_1")
    before.shutdown()
    execute("UPDATE runs SET expires_at = 1 WHERE id = ?", (run["id"],))
    after = RunManager(interval_s=0.005)
    runs.set_manager(after)
    after.add_end_listener(seen.append)
    assert after.resume() == []
    assert len(seen) == 1 and seen[0]["cause"] == "expired" and seen[0]["purchase_id"] == "p_1"
    assert after.workers == {}






def test_resume_skips_dead_runs(manager):
    run = referee.open_run("s_a", rules(), "practice", "finished")
    referee.stop(run["id"])
    assert manager.resume() == []


def test_shutdown_stops_all_threads_and_unhooks(wait_until):
    created = RunManager(interval_s=0.005)
    started = [created.start("s_a", rules(), "practice", f"bot {i}") for i in range(3)]
    threads = [created.workers[r["id"]][0] for r in started]
    created.shutdown()
    assert all(not t.is_alive() for t in threads)
    seen = []
    created.add_end_listener(seen.append)
    referee.stop(started[0]["id"])
    assert seen == []
    assert all(referee.get_run(r["id"])["status"] == "alive" for r in started[1:])


@pytest.fixture
def agent_calls(monkeypatch):
    calls = []

    def fake_agent(run_id, stop_event, interval_s):
        calls.append(run_id)
        stop_event.wait(5)

    monkeypatch.setattr("parable.bot_agent.run_agent", fake_agent)
    return calls


def test_start_dispatches_new_rules_to_run_agent(manager, agent_calls, wait_until, price_box):
    run = manager.start("s_a", agent_rules(), "practice", "agent")
    assert wait_until(lambda: agent_calls == [run["id"]])
    assert run["version_id"] == "v_test000001"




def test_practice_cap_counts_only_alive_practice_runs(manager, agent_calls, monkeypatch, price_box):
    from parable.config import get_settings
    monkeypatch.setenv("MAX_LIVE_RUNS_PER_ACCOUNT", "2")
    get_settings.cache_clear()
    first = manager.start("s_a", agent_rules(), "practice", "one")
    manager.start("s_a", agent_rules(), "practice", "two")
    with pytest.raises(MarketError) as caught:
        manager.start("s_a", agent_rules(), "practice", "three")
    assert caught.value.status == 429
    manager.start("s_a", agent_rules(), "track", "track")
    manager.start("s_a", agent_rules(), "probation", "probation")
    manager.start("s_b", agent_rules(), "practice", "other account")
    manager.stop(first["id"])
    assert manager.start("s_a", agent_rules(), "practice", "freed")["status"] == "alive"




def test_resume_loads_the_spec_by_version_id(monkeypatch, wait_until, price_box, feed):
    loaded = []
    signals = install_fake_lab(monkeypatch)
    import parable.lab.spec as fake_spec
    monkeypatch.setattr(fake_spec, "load_spec", lambda version_id: loaded.append(version_id) or FakeSpec())
    before = RunManager(interval_s=0.005)
    runs.set_manager(before)
    before.start("s_a", agent_rules(version_id="v_resumed001"), "practice", "agent")
    before.shutdown()
    loaded.clear()
    after = RunManager(interval_s=0.005)
    runs.set_manager(after)
    after.resume()
    assert wait_until(lambda: loaded == ["v_resumed001"])
    assert signals.decisions >= 0


def test_start_for_version_builds_rules(manager, agent_calls, feed, price_box):
    insert_version()
    run = manager.start_for_version("s_a", "v_test000001", "fake:BTCUSDT", "1h", "track", "tracked",
                                    listing_id="l_1", lease_seconds=500)
    assert run["quote"] == "USDT" and run["purpose"] == "track" and run["listing_id"] == "l_1"
    assert run["spec_hash"] == "ab" * 32 and run["cash_usd"] == 10_000 * USD
    assert run["rules"]["max_trade"] == run["rules"]["start_cash"] == 10_000 * USD
    assert run["rules"]["max_loss_bps"] == 2000 and run["expires_at"] - run["started_at"] == 500
    custom = manager.start_for_version("s_a", "v_test000001", "fake:BTCUSDT", "1h", "probation", "p",
                                       start_cash=50 * USD, max_loss_bps=300)
    assert custom["cash_usd"] == 50 * USD and custom["rules"]["max_trade"] == 50 * USD


def test_start_for_version_unknown_version(manager, feed):
    with pytest.raises(LabError) as caught:
        manager.start_for_version("s_a", "v_missing0001", "fake:BTCUSDT", "1h", "practice", "x")
    assert caught.value.status == 404


def test_poll_hooks_run_each_poll_and_are_guarded(manager, price_box):
    calls = []

    def broken():
        raise RuntimeError("boom")

    manager.add_poll_hook(broken)
    manager.add_poll_hook(lambda: calls.append(1))
    manager.add_poll_hook(manager.poll_hooks[1])
    manager.poll_once()
    manager.poll_once()
    assert calls == [1, 1] and len(manager.poll_hooks) == 2


def test_poll_once_ends_expired_agent_run(manager, agent_calls, monkeypatch, price_box):
    run = manager.start("s_a", agent_rules(lease_seconds=60), "practice", "short")
    monkeypatch.setattr(referee, "now", lambda: run["started_at"] + 61)
    ended = manager.poll_once()
    assert [r["cause"] for r in ended] == ["expired"]
