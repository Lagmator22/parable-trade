import json
import sys
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from parable import webhooks
from parable.config import Settings
from parable.db import reset_db, rows
from parable.paypal import set_paypal
from parable.paypal_mock import MockPayPal
from parable.webhooks import router

PAYPAL_HEADERS = {
    "PAYPAL-TRANSMISSION-ID": "t-1",
    "PAYPAL-TRANSMISSION-SIG": "sig",
}


class ScriptedPayPal(MockPayPal):
    def __init__(self, verdict=True, error=None):
        super().__init__(public_base_url="http://localhost:8000")
        self.verdict = verdict
        self.error = error
        self.calls = []

    def verify_webhook(self, headers, body, webhook_id):
        self.calls.append({"headers": headers, "body": body, "webhook_id": webhook_id})
        if self.error:
            raise self.error
        return self.verdict


def capture_event(event_id="WH-1", event_type="PAYMENT.CAPTURE.COMPLETED", resource=None):
    return {
        "id": event_id,
        "event_type": event_type,
        "resource": resource if resource is not None else {"id": "CAP-1", "status": "COMPLETED"},
    }


@pytest.fixture
def market_calls(monkeypatch):
    calls = []
    fake = SimpleNamespace(on_webhook=lambda event_type, resource: calls.append((event_type, resource)))
    monkeypatch.setitem(sys.modules, "parable.market", fake)
    return calls


@pytest.fixture
def paypal():
    scripted = ScriptedPayPal()
    set_paypal(scripted)
    yield scripted
    set_paypal(None)


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    reset_db(":memory:")
    monkeypatch.setattr(webhooks, "get_settings", lambda: Settings(_env_file=None, paypal_webhook_id="WEBHOOK-ID"))


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def post(client, event, headers=None):
    return client.post("/paypal/webhook", content=json.dumps(event), headers=headers or PAYPAL_HEADERS)


def stored():
    return rows("SELECT id, event_type, resource_id, verified FROM webhook_events ORDER BY rowid")


def test_verified_event_is_stored_and_dispatched(client, paypal, market_calls):
    response = post(client, capture_event())
    assert response.status_code == 200
    assert response.json()["verified"] is True
    assert stored() == [{"id": "WH-1", "event_type": "PAYMENT.CAPTURE.COMPLETED", "resource_id": "CAP-1", "verified": 1}]
    assert market_calls == [("PAYMENT.CAPTURE.COMPLETED", {"id": "CAP-1", "status": "COMPLETED"})]


def test_signature_check_receives_headers_body_and_webhook_id(client, paypal, market_calls):
    event = capture_event()
    post(client, event)
    call = paypal.calls[0]
    assert call["webhook_id"] == "WEBHOOK-ID"
    assert call["body"] == event
    assert call["headers"]["paypal-transmission-id"] == "t-1"


def test_unverified_event_is_stored_but_not_dispatched(client, paypal, market_calls):
    paypal.verdict = False
    assert post(client, capture_event()).status_code == 200
    assert stored()[0]["verified"] == 0
    assert market_calls == []


def test_missing_webhook_id_stores_unverified_without_calling_paypal(client, paypal, market_calls, monkeypatch):
    monkeypatch.setattr(webhooks, "get_settings", lambda: Settings(_env_file=None, paypal_webhook_id=""))
    assert post(client, capture_event()).status_code == 200
    assert stored()[0]["verified"] == 0
    assert paypal.calls == [] and market_calls == []


def test_signature_check_crash_counts_as_unverified(client, paypal, market_calls):
    paypal.error = RuntimeError("network down")
    assert post(client, capture_event()).status_code == 200
    assert stored()[0]["verified"] == 0
    assert market_calls == []


def test_duplicate_event_id_is_dispatched_once(client, paypal, market_calls):
    first = post(client, capture_event())
    second = post(client, capture_event())
    assert first.json()["stored"] is True
    assert second.status_code == 200 and second.json()["stored"] is False
    assert len(stored()) == 1
    assert len(market_calls) == 1


def test_forged_unverified_event_cannot_block_the_real_one(client, paypal, market_calls):
    paypal.verdict = False
    post(client, capture_event(resource={"id": "FORGED"}))
    paypal.verdict = True
    post(client, capture_event(resource={"id": "CAP-REAL"}))
    assert stored() == [{"id": "WH-1", "event_type": "PAYMENT.CAPTURE.COMPLETED", "resource_id": "CAP-REAL", "verified": 1}]
    assert market_calls == [("PAYMENT.CAPTURE.COMPLETED", {"id": "CAP-REAL"})]


def test_verified_event_is_never_overwritten_by_an_unverified_replay(client, paypal, market_calls):
    post(client, capture_event(resource={"id": "CAP-REAL"}))
    paypal.verdict = False
    post(client, capture_event(resource={"id": "FORGED"}))
    assert stored()[0]["resource_id"] == "CAP-REAL"
    assert len(market_calls) == 1


def test_unhandled_event_type_is_stored_without_dispatch(client, paypal, market_calls):
    post(client, capture_event(event_type="CUSTOMER.DISPUTE.CREATED"))
    assert len(stored()) == 1
    assert market_calls == []


@pytest.mark.parametrize("event_type", sorted(webhooks.HANDLED_EVENTS))
def test_every_handled_event_type_is_dispatched(client, paypal, market_calls, event_type):
    post(client, capture_event(event_type=event_type))
    assert [call[0] for call in market_calls] == [event_type]


def test_handler_failure_still_answers_200(client, paypal, monkeypatch):
    def explode(event_type, resource):
        raise RuntimeError("boom")

    monkeypatch.setitem(sys.modules, "parable.market", SimpleNamespace(on_webhook=explode))
    assert post(client, capture_event()).status_code == 200
    assert len(stored()) == 1


def test_missing_market_module_still_answers_200(client, paypal, monkeypatch):
    monkeypatch.setitem(sys.modules, "parable.market", None)
    assert post(client, capture_event()).status_code == 200
    assert len(stored()) == 1


@pytest.mark.parametrize("raw", [b"not json", b"[1, 2]", b"", b'"text"', b"x" * (webhooks.MAX_BODY_BYTES + 1)])
def test_garbage_bodies_answer_200_and_store_nothing(client, paypal, market_calls, raw):
    response = client.post("/paypal/webhook", content=raw, headers=PAYPAL_HEADERS)
    assert response.status_code == 200
    assert response.json()["ok"] is False
    assert stored() == [] and market_calls == []


def test_event_without_id_is_deduplicated_by_content(client, paypal, market_calls):
    event = {"event_type": "PAYMENT.CAPTURE.COMPLETED", "resource": {"id": "CAP-9"}}
    post(client, event)
    post(client, event)
    assert len(stored()) == 1
    assert len(market_calls) == 1


def test_non_object_resource_is_treated_as_empty(client, paypal, market_calls):
    post(client, {"id": "WH-2", "event_type": "PAYMENT.CAPTURE.COMPLETED", "resource": "oops"})
    assert market_calls == [("PAYMENT.CAPTURE.COMPLETED", {})]
    assert stored()[0]["resource_id"] == ""


def test_payout_batch_resource_id_comes_from_batch_header(client, paypal, market_calls):
    resource = {"batch_header": {"payout_batch_id": "PB-7", "batch_status": "SUCCESS"}}
    post(client, capture_event("WH-3", "PAYMENT.PAYOUTSBATCH.SUCCESS", resource))
    assert stored()[0]["resource_id"] == "PB-7"


def test_payout_item_resource_id_comes_from_item_id(client, paypal, market_calls):
    post(client, capture_event("WH-4", "PAYMENT.PAYOUTS-ITEM.SUCCEEDED", {"payout_item_id": "ITEM-3"}))
    assert stored()[0]["resource_id"] == "ITEM-3"


def test_recent_is_empty_at_first(client):
    assert client.get("/api/webhooks/recent").json() == []


def test_recent_lists_newest_first_and_caps_at_twenty(client, paypal, market_calls):
    for number in range(25):
        post(client, capture_event(f"WH-{number:02d}", resource={"id": f"CAP-{number}"}))
    recent = client.get("/api/webhooks/recent").json()
    assert len(recent) == 20
    assert recent[0]["id"] == "WH-24"
    assert recent[-1]["id"] == "WH-05"


def test_recent_exposes_type_verified_resource_and_time_only(client, paypal, market_calls):
    post(client, capture_event())
    entry = client.get("/api/webhooks/recent").json()[0]
    assert set(entry) == {"id", "event_type", "resource_id", "verified", "received_at"}
    assert entry["verified"] is True
    assert entry["event_type"] == "PAYMENT.CAPTURE.COMPLETED"
    assert entry["resource_id"] == "CAP-1"
    assert isinstance(entry["received_at"], int)


def test_unverified_events_are_not_listed_and_keep_no_body(client, paypal, market_calls):
    paypal.verdict = False
    post(client, capture_event(resource={"id": "CAP-1", "payload": "x" * 5000}))
    assert client.get("/api/webhooks/recent").json() == []
    stored = rows("SELECT verified, body_json FROM webhook_events")
    assert stored == [{"verified": 0, "body_json": ""}]


def test_unverified_rows_are_pruned(client, paypal, market_calls, monkeypatch):
    paypal.verdict = False
    monkeypatch.setattr(webhooks, "KEEP_UNVERIFIED", 3)
    for number in range(8):
        post(client, capture_event(event_id=f"WH-{number}"))
    assert len(rows("SELECT id FROM webhook_events")) == 3


def test_real_client_skips_paypal_for_foreign_cert_urls():
    from parable.paypal import PayPalClient, trusted_cert_url

    assert trusted_cert_url("https://api.paypal.com/v1/notifications/certs/x")
    assert not trusted_cert_url("https://evil.example.com/cert") and not trusted_cert_url("http://api.paypal.com/x")
    client = PayPalClient("id", "secret", "sandbox", http=SimpleNamespace(request=lambda *a, **k: 1 / 0))
    headers = {name: "x" for name in ("paypal-transmission-id", "paypal-transmission-time", "paypal-auth-algo",
                                      "paypal-transmission-sig")}
    headers["paypal-cert-url"] = "https://evil.example.com/cert"
    assert client.verify_webhook(headers, {}, "WH") is False
