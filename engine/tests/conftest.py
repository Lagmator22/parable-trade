import time

import pytest
from fastapi.testclient import TestClient

from market_support import install_manager
from parable import api, db, market, prices, referee, runs
from parable.config import get_settings

BLANK_KEYS = (
    "ANTHROPIC_API_KEY", "AUTOLOOPS_API_KEY", "GEMINI_API_KEY", "PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET",
    "PAYPAL_WEBHOOK_ID", "CLAUDE_MODELS", "GEMINI_MODELS", "GEMMA_MODELS",
)


def clear_engine_state() -> None:
    runs.set_manager(None)
    runs.shutdown_all()
    referee.clear_end_hooks()
    prices.stop_sampler()
    prices.set_price_source(None)


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
    yield
    clear_engine_state()
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
        assert wait_until(lambda: market.get_purchase(purchase_id)["status"] in statuses)
        return market.get_purchase(purchase_id)

    return wait


@pytest.fixture
def client(manager, tmp_path):
    with TestClient(api.create_app(tmp_path)) as running:
        yield running


@pytest.fixture
def seller_client(client):
    signed_in = client.post("/paypal/mock-login", data={"name": "Flow Seller", "email": "flow@example.com"},
                            follow_redirects=False)
    assert signed_in.status_code == 302
    return client
