import httpx
import pytest
from fastapi.testclient import TestClient

from api_support import LISTING_BODY
from parable import mcp_server


@pytest.fixture
def wired(seller_client, monkeypatch):
    seller_client.post("/api/listings", json=LISTING_BODY)
    monkeypatch.setattr(mcp_server, "get_client", lambda: ForwardingClient(seller_client))
    return seller_client


class ForwardingClient:
    def __init__(self, test_client: TestClient) -> None:
        self.test_client = test_client

    def __enter__(self):
        return self.test_client

    def __exit__(self, *exc):
        return False


def test_server_exposes_the_seven_tools():
    names = {tool.name for tool in mcp_server.mcp._tool_manager.list_tools()}
    assert names == {"find_bots", "due_diligence", "buy_bot", "purchase_status", "seller_record", "verify_ledger",
                     "market_stats"}
    assert mcp_server.mcp.name == "Parable"


def test_find_bots_returns_a_recommendation_with_compact_candidates(wired):
    found = mcp_server.find_bots("a careful bot", max_price_dollars=25)
    assert found["recommended_listing_id"] and found["by"] == "rules"
    candidate = found["candidates"][0]
    assert candidate["price_dollars"] == 20 and candidate["probation_minutes"] == 2
    assert candidate["seller"] == "Flow Seller" and "seller_record" not in candidate


def test_find_bots_respects_the_budget(wired):
    found = mcp_server.find_bots("anything", max_price_dollars=5)
    assert found["recommended_listing_id"] is None and found["candidates"] == []


def test_due_diligence_and_seller_record(wired):
    listing = wired.get("/api/listings").json()[0]
    assert mcp_server.due_diligence(listing["id"])["risk"] in ("low", "medium", "high")
    assert mcp_server.seller_record(listing["seller_id"])["seller"]["name"] == "Flow Seller"


def test_buy_bot_requires_a_human_and_marks_the_purchase_as_agent(wired):
    listing = wired.get("/api/listings").json()[0]
    bought = mcp_server.buy_bot(listing["id"])
    assert bought["approve_url"].startswith("http") and bought["buyer_token"] and "human" in bought["instruction"]
    status = mcp_server.purchase_status(bought["purchase_id"], bought["buyer_token"])
    assert status["status"] == "created" and status["via"] == "agent" and status["license"] is None


def test_purchase_status_with_a_wrong_token_never_returns_a_license(wired):
    listing = wired.get("/api/listings").json()[0]
    bought = mcp_server.buy_bot(listing["id"])
    assert mcp_server.purchase_status(bought["purchase_id"], "wrong")["license"] is None


def test_ledger_and_stats_tools(wired):
    assert mcp_server.verify_ledger()["ok"] is True
    assert mcp_server.market_stats()["listings"] == 1


def test_errors_come_back_as_data_not_exceptions(wired):
    assert mcp_server.buy_bot("l_missing") == {"error": "listing not found", "status": 404}
    assert mcp_server.purchase_status("p_missing", "t")["status"] == 404


def test_unreachable_server_is_reported(monkeypatch):
    def refuse(request):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(mcp_server, "get_client", lambda: httpx.Client(
        base_url="http://parable.invalid", transport=httpx.MockTransport(refuse)))
    assert mcp_server.market_stats() == {"error": "could not reach Parable: ConnectError"}
    assert mcp_server.find_bots("x") == {"error": "could not reach Parable: ConnectError"}


def test_client_uses_parable_url(monkeypatch):
    monkeypatch.setenv("PARABLE_URL", "http://example.test:9")
    assert str(mcp_server.get_client().base_url) == "http://example.test:9"
    monkeypatch.delenv("PARABLE_URL")
    assert str(mcp_server.get_client().base_url) == "http://localhost:8000"


def test_mock_transport_round_trip(monkeypatch):
    def handler(request):
        assert request.headers["x-buyer-token"] == "tok" and request.url.path == "/api/purchases/p_1"
        return httpx.Response(200, json={"status": "probation"})

    monkeypatch.setattr(mcp_server, "get_client", lambda: httpx.Client(
        base_url="http://parable.invalid", transport=httpx.MockTransport(handler)))
    assert mcp_server.purchase_status("p_1", "tok") == {"status": "probation"}
