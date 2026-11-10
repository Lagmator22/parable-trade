import re

from fastapi.testclient import TestClient

from market_support import USD

LISTING_BODY = {
    "title": "Flow Bot", "pitch": "Tested end to end.", "strategy": "yolo", "brain": "rule",
    "max_trade_usd": 100 * USD, "max_loss_bps": 100, "price_cents": 2000, "probation_s": 120,
    "min_return_bps": -50,
}


def order_from(approve_url: str) -> str:
    return re.search(r"order=([^&]+)", approve_url).group(1)


def approve_in_paypal(client: TestClient, purchase: dict) -> str:
    response = client.post("/paypal/mock-approve", data={"order": purchase["paypal_order_id"], "decision": "approve"},
                           follow_redirects=False)
    assert response.status_code == 303
    return response.headers["location"]


def buy_and_approve(client: TestClient, listing_id: str) -> dict:
    started = client.post("/api/purchases", json={"listing_id": listing_id}).json()
    landing = approve_in_paypal(client, started)
    assert client.get(landing, follow_redirects=False).status_code == 302
    return started
