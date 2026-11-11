import pytest
from fastapi.testclient import TestClient

from market_support import make_listing
from parable import api, guard, market
from parable.config import get_settings
from parable.lab import markets, quota


def scope(peer="10.0.0.1", forwarded=None):
    headers = [(b"x-forwarded-for", forwarded.encode())] if forwarded else []
    return {"client": (peer, 1234), "headers": headers}


def test_forwarded_header_is_ignored_without_a_trusted_proxy():
    assert guard.resolve_client_ip(scope("9.9.9.9", "1.1.1.1, 2.2.2.2")) == "9.9.9.9"


def test_only_the_last_hop_is_trusted_behind_one_proxy(monkeypatch):
    monkeypatch.setenv("TRUST_PROXY", "1")
    get_settings.cache_clear()
    assert guard.resolve_client_ip(scope("10.0.0.1", "6.6.6.6, 2.2.2.2")) == "2.2.2.2"
    assert guard.resolve_client_ip(scope("10.0.0.1")) == "10.0.0.1"


def test_fresh_visitors_share_one_address_allowance():
    for number in range(10):
        try:
            quota.take_free_try(f"v_fresh{number:012d}")
        except Exception:
            break
    state = quota.free_tries("ip:" + quota.ip_visitor(guard.client_ip.get()))
    assert state["used"] == quota.IP_FREE_FACTOR * get_settings().ai_free_tries_per_day


def test_address_rate_bucket_catches_cookie_rotation():
    with pytest.raises(Exception) as limited:
        for number in range(40):
            quota.hit_with_address(f"lab:v_{number:016d}", 5, 60)
    assert getattr(limited.value, "status", None) == 429


def test_large_bodies_are_refused(client):
    big = client.post("/api/lab/validate", content=b"x" * 2_000_000, headers={"content-type": "application/json"})
    assert big.status_code == 413


def test_security_headers_are_on_every_response(client):
    headers = client.get("/api/info").headers
    assert headers["x-content-type-options"] == "nosniff" and headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in headers["content-security-policy"]
    assert "paypal.com" in headers["content-security-policy"]
    assert "referrer-policy" in headers and "strict-transport-security" not in headers


def test_hsts_is_sent_on_https(monkeypatch, client):
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://example.test")
    get_settings.cache_clear()
    assert "strict-transport-security" in client.get("/api/info").headers


def test_docs_are_off_in_production(monkeypatch, tmp_path):
    monkeypatch.setenv("PARABLE_ENV", "production")
    get_settings.cache_clear()
    app = TestClient(api.create_app(tmp_path))
    assert app.get("/docs").status_code == 404 and app.get("/openapi.json").status_code == 404


def test_shopper_is_rate_limited(client):
    codes = [client.post("/api/shopper", json={"query": "x"}).status_code for _ in range(9)]
    assert 429 in codes


def test_market_routes_are_rate_limited_and_validate_symbols(client):
    assert client.get("/api/markets/latest", params={"symbol": "a b\n"}).status_code == 400
    codes = {client.get("/api/markets/latest", params={"symbol": "sample:BTCUSDT"}).status_code for _ in range(70)}
    assert 429 in codes


def test_public_listing_reads_never_call_a_provider(monkeypatch, manager):
    make_listing()

    def boom(*args, **kwargs):
        raise AssertionError("provider called")

    monkeypatch.setattr(markets, "symbol_info", boom)
    monkeypatch.setattr(markets, "candles", boom)
    assert market.list_listings()[0]["kind"] == "crypto"


def test_oversized_webhook_is_refused(client):
    assert client.post("/paypal/webhook", content=b"{" + b" " * 300_000 + b"}").status_code == 413


def test_webhook_endpoint_is_rate_limited(client):
    body = {"id": "WH-1", "event_type": "X", "resource": {}}
    codes = {client.post("/paypal/webhook", json=body).status_code for _ in range(70)}
    assert 429 in codes
