import httpx
import pytest
from fastapi.testclient import TestClient

from market_support import make_listing
from parable import mcp_server
from parable.db import one


@pytest.fixture
def wired(seller_client, manager, monkeypatch):
    seller = one("SELECT id FROM sellers WHERE email = ?", ("flow@example.com",))
    make_listing(seller, title="Flow Agent", price_cents=2000)
    monkeypatch.setattr(mcp_server, "get_client", lambda: ForwardingClient(seller_client))
    return seller_client


class ForwardingClient:
    def __init__(self, test_client: TestClient) -> None:
        self.test_client = test_client

    def __enter__(self):
        return self.test_client

    def __exit__(self, *exc):
        return False


def test_server_exposes_the_nine_tools():
    names = {tool.name for tool in mcp_server.mcp._tool_manager.list_tools()}
    assert names == {"find_agents", "due_diligence", "proof", "rerun_proof", "test_drive", "buy_link",
                     "seller_record", "verify_ledger", "market_stats"}
    assert mcp_server.mcp.name == "Parable"


def test_find_agents_returns_a_recommendation_with_compact_candidates(wired):
    found = mcp_server.find_agents("a careful agent", max_price_dollars=25)
    assert found["recommended_listing_id"] and found["by"] == "rules"
    candidate = found["candidates"][0]
    assert candidate["price_dollars"] == 20 and candidate["asset"] == "fake:BTCUSDT" and candidate["mode"] == "hold"
    assert candidate["seller"] == "Flow Seller" and "seller_record" not in candidate and "spec" not in candidate
    assert mcp_server.find_agents("x", kind="stocks")["candidates"] == []
    assert len(mcp_server.find_agents("x", kind="crypto")["candidates"]) == 1


def test_find_agents_respects_the_budget(wired):
    found = mcp_server.find_agents("anything", max_price_dollars=5)
    assert found["recommended_listing_id"] is None and found["candidates"] == []


def test_due_diligence_and_seller_record(wired):
    listing = wired.get("/api/listings").json()[0]
    assert mcp_server.due_diligence(listing["id"])["risk"] in ("low", "medium", "high")
    assert mcp_server.seller_record(listing["seller"]["id"])["seller"]["name"] == "Flow Seller"


def test_proof_rerun_and_test_drive_tools(wired):
    listing = wired.get("/api/listings").json()[0]
    shown = mcp_server.proof(listing["id"])
    assert shown["result_hash"] and shown["metrics"]["trades"] == listing["headline"]["trades"]
    again = mcp_server.rerun_proof(listing["id"])
    assert again["match"] is True and again["claimed_hash"] == again["rerun_hash"] == shown["result_hash"]
    drive = mcp_server.test_drive(listing["id"], symbol="fake:ETHUSDT")
    assert drive["data"]["symbol"] == "fake:ETHUSDT" and drive["claim_metrics"]


def test_buy_link_points_a_human_at_the_listing(wired, monkeypatch):
    listing = wired.get("/api/listings").json()[0]
    monkeypatch.setenv("PARABLE_URL", "http://example.test:9/")
    link = mcp_server.buy_link(listing["id"])
    assert link["url"] == f"http://example.test:9/#agent/{listing['id']}" and "human" in link["instruction"]
    assert not hasattr(mcp_server, "buy_bot") and not hasattr(mcp_server, "purchase_status")


def test_ledger_and_stats_tools(wired):
    assert mcp_server.verify_ledger()["ok"] is True
    stats = mcp_server.market_stats()
    assert stats["listings"] == 1 and stats["agents"] == 1 and stats["proofs"] == 1


def test_errors_come_back_as_data_not_exceptions(wired):
    assert mcp_server.buy_link("l_missing")["status"] == 404
    assert mcp_server.proof("l_missing")["status"] == 404
    assert mcp_server.rerun_proof("l_missing")["status"] == 404


def test_unreachable_server_is_reported(monkeypatch):
    def refuse(request):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(mcp_server, "get_client", lambda: httpx.Client(
        base_url="http://parable.invalid", transport=httpx.MockTransport(refuse)))
    assert mcp_server.market_stats() == {"error": "could not reach Parable: ConnectError"}
    assert mcp_server.find_agents("x") == {"error": "could not reach Parable: ConnectError"}


def test_client_uses_parable_url(monkeypatch):
    monkeypatch.setenv("PARABLE_URL", "http://example.test:9")
    assert str(mcp_server.get_client().base_url) == "http://example.test:9"
    monkeypatch.delenv("PARABLE_URL")
    assert str(mcp_server.get_client().base_url) == "http://localhost:8000"


def test_mock_transport_round_trip(monkeypatch):
    def handler(request):
        assert request.url.path == "/api/listings/l_1/diligence"
        return httpx.Response(200, json={"risk": "low"})

    monkeypatch.setattr(mcp_server, "get_client", lambda: httpx.Client(
        base_url="http://parable.invalid", transport=httpx.MockTransport(handler)))
    assert mcp_server.due_diligence("l_1") == {"risk": "low"}
