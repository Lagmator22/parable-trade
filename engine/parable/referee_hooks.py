import logging
from typing import Callable

log = logging.getLogger("parable.referee")

_end_hooks: list[Callable[[dict], None]] = []


def add_end_hook(hook: Callable[[dict], None]) -> None:
    if hook not in _end_hooks:
        _end_hooks.append(hook)


def remove_end_hook(hook: Callable[[dict], None]) -> None:
    if hook in _end_hooks:
        _end_hooks.remove(hook)


def clear_end_hooks() -> None:
    _end_hooks.clear()


def announce_ended(ended: list[dict]) -> None:
    from parable import referee

    for run in ended:
        final = referee.get_run(run["id"])
        for hook in list(_end_hooks):
            try:
                hook(final)
            except Exception:
                log.exception("end hook failed for run %s", run["id"])
