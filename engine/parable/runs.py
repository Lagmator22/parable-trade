import json
import logging
import threading
from typing import Callable

from parable import bot_runner, referee
from parable.config import get_settings
from parable.models import BotRules

log = logging.getLogger("parable.runs")

POLL_EVERY_S = 3
JOIN_TIMEOUT_S = 2
ALL_ALIVE_RUNS = 100_000

_live_managers: list["RunManager"] = []


class RunManager:
    def __init__(self, interval_s: float | None = None) -> None:
        self.interval_s = get_settings().bot_interval_s if interval_s is None else interval_s
        self.listeners: list[Callable[[dict], None]] = []
        self.workers: dict[int, tuple[threading.Thread, threading.Event]] = {}
        self.workers_lock = threading.Lock()
        self.poller: threading.Thread | None = None
        self.poller_stop = threading.Event()
        referee.add_end_hook(self.dispatch_end)
        _live_managers.append(self)

    def add_end_listener(self, listener: Callable[[dict], None]) -> None:
        self.listeners.append(listener)

    def dispatch_end(self, run: dict) -> None:
        self.signal_stop(run["id"])
        for listener in list(self.listeners):
            try:
                listener(run)
            except Exception:
                log.exception("end listener failed for run %s", run["id"])

    def signal_stop(self, run_id: int) -> None:
        with self.workers_lock:
            worker = self.workers.get(run_id)
        if worker is not None:
            worker[1].set()

    def start(self, seller_id: str, rules: BotRules, purpose: str, name: str, listing_id: str | None = None,
              purchase_id: str | None = None) -> dict:
        run = referee.open_run(seller_id, rules, purpose, name, listing_id, purchase_id)
        self.spawn(run["id"], rules)
        return run

    def spawn(self, run_id: int, rules: BotRules) -> None:
        with self.workers_lock:
            existing = self.workers.get(run_id)
            if existing is not None and existing[0].is_alive():
                return
            stop_event = threading.Event()
            thread = threading.Thread(target=self.work, args=(run_id, rules, stop_event), daemon=True,
                                      name=f"bot-run-{run_id}")
            self.workers[run_id] = (thread, stop_event)
        thread.start()

    def work(self, run_id: int, rules: BotRules, stop_event: threading.Event) -> None:
        try:
            bot_runner.run_bot(run_id, rules, stop_event, self.interval_s)
        except Exception:
            log.exception("bot thread for run %s crashed", run_id)

    def stop(self, run_id: int, cause: str = "stopped") -> dict:
        self.signal_stop(run_id)
        return referee.stop(run_id, cause)

    def poll_once(self) -> list[dict]:
        ended = []
        for run in referee.list_runs(status="alive", limit=ALL_ALIVE_RUNS):
            closed = referee.check(run["id"])
            if closed is not None:
                ended.append(closed)
        return ended

    def poll_loop(self, every_s: float) -> None:
        while not self.poller_stop.wait(every_s):
            try:
                self.poll_once()
            except Exception:
                log.exception("run poll failed")

    def start_poller(self, every_s: float = POLL_EVERY_S) -> None:
        if self.poller is not None and self.poller.is_alive():
            return
        self.poller_stop.clear()
        self.poller = threading.Thread(target=self.poll_loop, args=(every_s,), daemon=True, name="run-poller")
        self.poller.start()

    def resume(self) -> list[int]:
        resumed = []
        for run in referee.list_runs(status="alive", limit=ALL_ALIVE_RUNS):
            if referee.check(run["id"]) is None:
                self.spawn(run["id"], BotRules.model_validate(json.loads(run["rules_json"])))
                resumed.append(run["id"])
        return resumed

    def shutdown(self) -> None:
        self.poller_stop.set()
        with self.workers_lock:
            workers = list(self.workers.values())
        for thread, stop_event in workers:
            stop_event.set()
        for thread, _ in workers:
            thread.join(timeout=JOIN_TIMEOUT_S)
        if self.poller is not None:
            self.poller.join(timeout=JOIN_TIMEOUT_S)
        referee.remove_end_hook(self.dispatch_end)
        if self in _live_managers:
            _live_managers.remove(self)


_manager: RunManager | None = None


def shutdown_all() -> None:
    for manager in list(_live_managers):
        manager.shutdown()


def get_manager() -> RunManager:
    global _manager
    if _manager is None:
        _manager = RunManager()
    return _manager


def set_manager(manager: RunManager | None) -> None:
    global _manager
    if _manager is not None and _manager is not manager:
        _manager.shutdown()
    _manager = manager
