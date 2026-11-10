import threading

import pytest

from parable.errors import LabError
from parable.lab import jobs


@pytest.fixture(autouse=True)
def clean_jobs():
    jobs.clear()
    yield
    jobs.clear()


def wait_for(job_id, owner, statuses, wait_until):
    assert wait_until(lambda: jobs.get(job_id, owner)["status"] in statuses)
    return jobs.get(job_id, owner)


def test_job_runs_reports_progress_and_result(wait_until):
    gate, seen = threading.Event(), threading.Event()

    def work(progress):
        progress(0.4, "halfway")
        seen.set()
        gate.wait(5)
        return {"answer": 42}

    job_id = jobs.start("benchmark", "s_a", work)
    assert job_id.startswith("j_") and len(job_id) == 12
    assert seen.wait(5)
    mid = jobs.get(job_id, "s_a")
    assert mid["status"] == "running" and mid["progress"] == 0.4 and mid["message"] == "halfway"
    assert mid["result"] is None and mid["kind"] == "benchmark" and "owner_id" not in mid
    gate.set()
    done = wait_for(job_id, "s_a", ("done",), wait_until)
    assert done["progress"] == 1.0 and done["result"] == {"answer": 42} and done["error"] is None
    assert set(done) == {"id", "kind", "status", "progress", "message", "result", "error", "created_at"}


def test_progress_is_clamped(wait_until):
    def work(progress):
        progress(7, "x" * 500)
        progress(-3, "y")
        return {}

    job_id = jobs.start("k", "s_a", work)
    done = wait_for(job_id, "s_a", ("done",), wait_until)
    assert done["progress"] == 1.0


def test_other_owner_gets_404():
    job_id = jobs.start("k", "s_a", lambda progress: {})
    for owner in ("s_b", ""):
        with pytest.raises(LabError) as err:
            jobs.get(job_id, owner)
        assert err.value.status == 404
    with pytest.raises(LabError):
        jobs.get("j_missing", "s_a")


def test_errors_become_job_errors_without_internals(wait_until):
    def lab_fail(progress):
        raise LabError(502, "bad_output", "model said nonsense")

    def crash(progress):
        raise RuntimeError("secret /path/to/file.py line 3")

    a = jobs.start("k", "s_a", lab_fail)
    assert wait_for(a, "s_a", ("error",), wait_until)["error"] == "model said nonsense"
    b = jobs.start("k", "s_a", crash)
    failed = wait_for(b, "s_a", ("error",), wait_until)
    assert failed["error"] == "the job failed" and failed["result"] is None


def test_unfinished_jobs_per_owner_are_capped(wait_until):
    gate = threading.Event()
    ids = [jobs.start("k", "s_a", lambda progress: gate.wait(5) and {}) for _ in range(2)]
    with pytest.raises(LabError) as err:
        jobs.start("k", "s_a", lambda progress: {})
    assert err.value.status == 429 and err.value.code == "rate_limited"
    other = jobs.start("k", "s_b", lambda progress: {})
    wait_for(other, "s_b", ("done",), wait_until)
    gate.set()
    for job_id in ids:
        wait_for(job_id, "s_a", ("done",), wait_until)
    assert jobs.start("k", "s_a", lambda progress: {})


def test_finished_jobs_are_kept_one_hour(wait_until):
    now = [1000.0]
    jobs.clock = lambda: now[0]
    try:
        job_id = jobs.start("k", "s_a", lambda progress: {"x": 1})
        wait_for(job_id, "s_a", ("done",), wait_until)
        now[0] += 3500
        assert jobs.get(job_id, "s_a")["status"] == "done"
        now[0] += 200
        with pytest.raises(LabError) as err:
            jobs.get(job_id, "s_a")
        assert err.value.status == 404
    finally:
        import time

        jobs.clock = time.time
