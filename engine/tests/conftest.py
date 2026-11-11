import time

import pytest
from fastapi.testclient import TestClient

from market_support import install_manager, purchase_row
from parable import api, db, diligence, listings, prices, referee, runs
from parable.config import get_settings
from parable.paypal import set_paypal
from parable.lab import datasets, jobs, markets, quota

BLANK_KEYS = (
    "ANTHROPIC_API_KEY", "AUTOLOOPS_API_KEY", "GEMINI_API_KEY", "PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET",
    "PAYPAL_WEBHOOK_ID", "CLAUDE_MODELS", "GEMINI_MODELS", "GEMMA_MODELS",
)


def clear_engine_state() -> None:
    runs.set_manager(None)
    runs.shutdown_all()
    referee.clear_end_hooks()
    prices.set_price_source(None)
    set_paypal(None)


@pytest.fixture(autouse=True)
def isolated_engine(monkeypatch):
    for key in BLANK_KEYS:
        monkeypatch.setenv(key, "")
    monkeypatch.setenv("PRICE_SOURCE", "sim")
    monkeypatch.setenv("MARKETS_OFFLINE", "1")
    monkeypatch.setenv("PARABLE_MOCK_PAYPAL", "1")
    get_settings.cache_clear()
    clear_engine_state()
    db.reset_db(":memory:")
    markets.reset_providers(offline=True)
    markets.clear_cache()
    jobs.clear()
    quota.limiter.clear()
    datasets.clear_drafts()
    diligence.clear_cache()
    listings.reset_throttle()
    yield
    clear_engine_state()
    markets.set_clock(None)
    markets.reset_providers(offline=True)
    get_settings.cache_clear()


class PriceBox:
    def __init__(self, dollars: float = 3000) -> None:
        self.value = int(dollars * 10**8)

    def __call__(self) -> int:
        return self.value

    def set(self, dollars: float) -> None:
        self.value = int(dollars * 10**8)


@pytest.fixture
def price_box():
    box = PriceBox()
    prices.set_price_source(box)
    return box


@pytest.fixture
def wait_until():
    def wait(predicate, timeout: float = 5.0) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if predicate():
                return True
            time.sleep(0.01)
        return bool(predicate())

    return wait


@pytest.fixture
def manager():
    return install_manager()


@pytest.fixture
def settled(wait_until):
    def wait(purchase_id: str, statuses: tuple[str, ...]) -> dict:
        assert wait_until(lambda: purchase_row(purchase_id)["status"] in statuses)
        return purchase_row(purchase_id)

    return wait


@pytest.fixture
def client(manager, tmp_path):
    with TestClient(api.create_app(tmp_path)) as running:
        yield running


def sign_in(session: TestClient, name: str, email: str) -> TestClient:
    signed_in = session.post("/paypal/mock-login", data={"name": name, "email": email}, follow_redirects=False)
    assert signed_in.status_code == 302
    return session


@pytest.fixture
def seller_client(client):
    return sign_in(client, "Flow Seller", "flow@example.com")


@pytest.fixture
def buyer_client(client):
    return sign_in(TestClient(client.app), "Flow Buyer", "buyer@example.com")
