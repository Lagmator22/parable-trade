import time

from fastapi import FastAPI
from fastapi.testclient import TestClient

from lab_support import make_bars
from parable import agents, db, identity, routes_agents, routes_lab, routes_runs, runs
from parable.api_support import install_error_handlers
from parable.lab import datasets, jobs, llm, markets, quota
from parable.lab.templates import template_spec

SYMBOL = "fake:BTCUSDT"
INTERVAL = "1h"


def make_app() -> FastAPI:
    app = FastAPI()
    install_error_handlers(app)
    for router in (routes_lab.router, routes_agents.router, routes_runs.router):
        app.include_router(router)
    return app


def make_account(name: str = "Ada") -> dict:
    return identity.upsert_seller("PAYER-" + name, name, f"{name.lower()}@example.com", True)


def make_client(account: dict | None = None) -> TestClient:
    client = TestClient(make_app())
    if account is not None:
        token = identity.sign(identity.SESSION_SALT, {"seller_id": account["id"]})
        client.cookies.set(identity.SESSION_COOKIE, token)
    return client


def reset_lab_state() -> None:
    jobs.clear()
    quota.limiter.clear()
    datasets.clear_drafts()
    markets.clear_cache()
    quota.set_clock(None)


def spec_dict(**over) -> dict:
    return {**template_spec("trend", SYMBOL, INTERVAL).model_dump(), **over}


def new_agent(owner: dict, name: str = "Agent") -> dict:
    return agents.create_agent(owner["id"], name, SYMBOL, INTERVAL)


def new_version(owner: dict, agent: dict, **over) -> dict:
    from parable.lab.spec import parse_spec

    return agents.save_version(owner["id"], agent["id"], parse_spec(spec_dict(**over)), "buy dips")


def add_listing(owner: dict, version_id: str, proof_id: str | None = None, **fields) -> str:
    listing_id = "l_" + str(time.time_ns())[-10:]
    values = {"id": listing_id, "seller_id": owner["id"], "title": "T", "active": 1, "version_id": version_id,
              "proof_id": proof_id, "symbol": SYMBOL, "interval": INTERVAL, "allow_test_drive": 1, **fields}
    cols = ",".join(values)
    db.execute(f"INSERT INTO listings ({cols}) VALUES ({','.join('?' for _ in values)})", tuple(values.values()))
    return listing_id


def install_runs():
    manager = runs.RunManager(interval_s=3600)
    runs.set_manager(manager)
    return manager


def wait_job(client: TestClient, job_id: str, wait_until, **kw) -> dict:
    assert wait_until(lambda: client.get(f"/api/jobs/{job_id}", **kw).json()["status"] in ("done", "error"))
    return client.get(f"/api/jobs/{job_id}", **kw).json()


def fake_chat(monkeypatch, replies):
    seen = []
    queue = list(replies)

    def chat(auth, prompt, **kwargs):
        seen.append(auth)
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(llm, "chat_json", chat)
    return seen


def llm_spec(**over) -> dict:
    keys = ("name", "summary", "params", "entry", "exit", "size_pct", "stop_loss_pct", "take_profit_pct",
            "trailing_stop_pct", "fee_bps", "slippage_bps")
    base = {k: v for k, v in spec_dict().items() if k in keys}
    return {**base, **over}


def csv_file(n: int = 60) -> bytes:
    lines = ["date,close"] + [f"2024-01-{(i % 28) + 1:02d}T00:00:00,{100 + i}" for i in range(n)]
    return "\n".join(lines).encode()


def daily_csv(n: int = 60) -> bytes:
    rows = make_bars(n, start_t=1_700_000_000, interval_s=86400)
    return ("time,open,high,low,close,volume\n" + "\n".join(",".join(str(x) for x in r) for r in rows)).encode()


import pytest


@pytest.fixture(autouse=True)
def clean_lab():
    reset_lab_state()
    install_runs()
    yield
    reset_lab_state()
