import secrets
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from parable.config import get_settings
from parable.errors import LabError

KEEP_S = 3600
WORKERS = 4
MESSAGE_CHARS = 200

_lock = threading.Lock()
_jobs: dict[str, dict] = {}
_pool: ThreadPoolExecutor | None = None
clock: Callable[[], float] = time.time


def pool() -> ThreadPoolExecutor:
    global _pool
    if _pool is None:
        _pool = ThreadPoolExecutor(max_workers=WORKERS, thread_name_prefix="lab-job")
    return _pool


def prune() -> None:
    cutoff = clock() - KEEP_S
    for job_id in [j for j, job in _jobs.items() if job["status"] in ("done", "error") and job["created_at"] < cutoff]:
        del _jobs[job_id]


def update(job_id: str, **fields) -> None:
    with _lock:
        if job_id in _jobs:
            _jobs[job_id].update(fields)


def run(job_id: str, fn: Callable[[Callable[[float, str], None]], dict]) -> None:
    update(job_id, status="running")

    def progress(fraction: float | None = None, message: str | None = None, partial: dict | None = None) -> None:
        fields: dict = {}
        if fraction is not None:
            fields["progress"] = min(1.0, max(0.0, float(fraction)))
        if message is not None:
            fields["message"] = str(message)[:MESSAGE_CHARS]
        if partial is not None:
            fields["result"] = partial
        update(job_id, **fields)

    try:
        result = fn(progress)
    except LabError as err:
        update(job_id, status="error", error=err.detail)
    except Exception:
        update(job_id, status="error", error="the job failed")
    else:
        update(job_id, status="done", progress=1.0, result=result)


def start(kind: str, owner_id: str, fn: Callable[[Callable[[float, str], None]], dict]) -> str:
    with _lock:
        prune()
        busy = sum(1 for j in _jobs.values() if j["owner_id"] == owner_id and j["status"] in ("queued", "running"))
        if busy >= get_settings().max_jobs_per_account:
            raise LabError(429, "rate_limited", "you already have jobs running, wait for one to finish", {"retry_after": 10})
        job_id = "j_" + secrets.token_hex(5)
        _jobs[job_id] = {"id": job_id, "kind": kind, "owner_id": owner_id, "status": "queued", "progress": 0.0,
                         "message": "", "result": None, "error": None, "created_at": clock()}
    pool().submit(run, job_id, fn)
    return job_id


def get(job_id: str, owner_id: str) -> dict:
    with _lock:
        prune()
        job = _jobs.get(job_id)
        if job is None or job["owner_id"] != owner_id:
            raise LabError(404, "not_found", "no such job")
        return {k: v for k, v in job.items() if k != "owner_id"}


def clear() -> None:
    with _lock:
        _jobs.clear()
