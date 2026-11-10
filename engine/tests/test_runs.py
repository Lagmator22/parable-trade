import threading

import pytest

from parable import ledger, referee, runs
from parable.db import execute
from parable.models import BotRules
from parable.runs import RunManager

USD = 1_000_000


def rules(**overrides) -> BotRules:
    base = {"strategy": "yolo", "max_trade_usd": 100 * USD, "max_loss_bps": 5000, "lease_seconds": 120}
    return BotRules(**{**base, **overrides})


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


def test_start_runs_a_bot_thread_that_trades(manager, wait_until):
    run = manager.start("s_a", rules(), "practice", "live bot")
    assert run["status"] == "alive"
    assert wait_until(lambda: referee.get_run(run["id"])["trades"] >= 2)
    assert manager.workers[run["id"]][0].daemon


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


def test_listener_called_exactly_once_with_final_run(manager, wait_until, monkeypatch):
    seen = []
    manager.add_end_listener(seen.append)
    run = manager.start("s_a", rules(lease_seconds=60), "practice", "short")
    monkeypatch.setattr(referee, "now", lambda: run["expires_at"] + 1)
    assert wait_until(lambda: len(seen) >= 1)
    manager.poll_once()
    manager.poll_once()
    manager.stop(run["id"])
    threading.Event().wait(0.05)
    assert len(seen) == 1
    assert seen[0]["id"] == run["id"] and seen[0]["status"] == "dead" and seen[0]["cause"] == "expired"
    assert "equity_usd" in seen[0] and seen[0]["final_equity_usd"] is not None


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


def test_loss_limit_ends_run_via_bot_thread(manager, price_box, wait_until):
    seen = []
    manager.add_end_listener(seen.append)
    run = manager.start("s_a", rules(max_trade_usd=1000 * USD, max_loss_bps=300), "practice", "crash")
    assert wait_until(lambda: referee.get_run(run["id"])["trades"] >= 1)
    price_box.set(1000)
    assert wait_until(lambda: len(seen) == 1)
    assert seen[0]["cause"] == "loss_limit"
    assert wait_until(lambda: not manager.workers[run["id"]][0].is_alive())


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


def test_resume_restarts_alive_runs_after_restart(wait_until):
    before = RunManager(interval_s=0.005)
    runs.set_manager(before)
    run = before.start("s_a", rules(), "practice", "survivor")
    before.shutdown()
    trades_at_crash = referee.get_run(run["id"])["trades"]
    after = RunManager(interval_s=0.005)
    runs.set_manager(after)
    assert after.workers == {}
    assert after.resume() == [run["id"]]
    assert wait_until(lambda: referee.get_run(run["id"])["trades"] > trades_at_crash)
    assert after.workers[run["id"]][0].is_alive()


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


def test_resume_ends_runs_already_past_loss_limit(price_box):
    seen = []
    first = RunManager(interval_s=1000)
    runs.set_manager(first)
    run = first.start("s_a", rules(strategy="momentum", max_trade_usd=1000 * USD, max_loss_bps=300), "practice",
                      "hurt")
    first.shutdown()
    referee.trade(run["id"], "buy", 1000 * USD, "in")
    price_box.set(1500)
    second = RunManager(interval_s=1000)
    runs.set_manager(second)
    second.add_end_listener(seen.append)
    assert second.resume() == []
    assert seen[0]["cause"] == "loss_limit"


def test_resume_does_not_double_spawn(manager):
    run = manager.start("s_a", rules(), "practice", "once")
    thread = manager.workers[run["id"]][0]
    assert manager.resume() == [run["id"]]
    assert manager.workers[run["id"]][0] is thread


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
