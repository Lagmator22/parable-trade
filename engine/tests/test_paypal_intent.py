import httpx
import pytest

from paypal_support import body_of, build
from parable.paypal import PayPalError
from parable.paypal_mock import MockPayPal


@pytest.fixture
def mock():
    return MockPayPal(public_base_url="http://parable.test/")


def order_for(mock, intent, custom_id="p_1"):
    return mock.create_order(2500, "Agent", custom_id, "http://r", "http://c", intent=intent)


def failure(call, *arguments):
    with pytest.raises(PayPalError) as problem:
        call(*arguments)
    return problem.value.name


def test_default_intent_is_authorize(mock):
    order = mock.create_order(2500, "Agent", "p_1", "http://r", "http://c")
    assert mock.get_order(order["id"])["intent"] == "AUTHORIZE"


def test_unknown_intent_is_rejected(mock):
    assert failure(lambda: order_for(mock, "SELL")) == "INVALID_PARAMETER_VALUE"


def test_capture_order_happy_path_and_payer(mock):
    order = order_for(mock, "CAPTURE")
    assert "payer" not in mock.get_order(order["id"])
    mock.approve(order["id"], "buyer@example.com", "PAYER-1")
    assert mock.get_order(order["id"])["payer"] == {"payer_id": "PAYER-1", "email": "buyer@example.com"}
    capture = mock.capture_order(order["id"])
    assert capture["capture_id"].startswith("MOCK-CAPTURE-")
    assert (capture["amount_cents"], capture["payer_id"], capture["status"]) == (2500, "PAYER-1", "COMPLETED")


def test_capture_requires_approval_and_never_twice(mock):
    order = order_for(mock, "CAPTURE")
    assert failure(mock.capture_order, order["id"]) == "ORDER_NOT_APPROVED"
    mock.approve(order["id"])
    mock.capture_order(order["id"])
    assert failure(mock.capture_order, order["id"]) == "ORDER_ALREADY_CAPTURED"


def test_intent_mismatch_both_ways(mock):
    capture_order = order_for(mock, "CAPTURE", "p_1")
    authorize_order = order_for(mock, "AUTHORIZE", "p_2")
    mock.approve(capture_order["id"])
    mock.approve(authorize_order["id"])
    assert failure(mock.authorize_order, capture_order["id"]) == "ORDER_INTENT_MISMATCH"
    assert failure(mock.capture_order, authorize_order["id"]) == "ORDER_INTENT_MISMATCH"


def test_fail_next_injects_one_failure_per_operation(mock):
    mock.fail_next("create_payout", "INSTRUMENT_DECLINED")
    assert failure(mock.create_payout, "b1", "a@b.c", 100, "n") == "INSTRUMENT_DECLINED"
    assert mock.create_payout("b1", "a@b.c", 100, "n")["batch_status"] == "SUCCESS"
    order = order_for(mock, "CAPTURE")
    mock.approve(order["id"])
    mock.fail_next("capture_order", "TRANSIENT")
    assert failure(mock.capture_order, order["id"]) == "TRANSIENT"
    assert mock.capture_order(order["id"])["status"] == "COMPLETED"


CAPTURED = {"id": "O1", "payer": {"payer_id": "PY", "email_address": "b@x.io"},
            "purchase_units": [{"payments": {"captures": [
                {"id": "CAP-1", "status": "COMPLETED", "amount": {"currency_code": "USD", "value": "25.00"}}]}}]}


def test_real_client_create_order_sends_capture_intent():
    created = {"id": "O1", "status": "CREATED", "links": [{"rel": "payer-action", "href": "https://p/approve"}]}
    client, recorder = build({("POST", "/v2/checkout/orders"): httpx.Response(201, json=created)})
    client.create_order(2500, "Agent", "p_abc", "https://r", "https://c", intent="CAPTURE")
    assert body_of(recorder.sent("POST", "/v2/checkout/orders")[0])["intent"] == "CAPTURE"


def test_real_client_capture_order_reads_capture():
    client, recorder = build({("POST", "/v2/checkout/orders/O1/capture"): httpx.Response(201, json=CAPTURED)})
    assert client.capture_order("O1") == {
        "capture_id": "CAP-1", "status": "COMPLETED", "amount_cents": 2500, "payer_email": "b@x.io",
        "payer_id": "PY"}
    assert recorder.sent("POST", "/v2/checkout/orders/O1/capture")[0].headers["paypal-request-id"] == "O1:capture"


def test_real_client_capture_order_missing_capture():
    client, _ = build({("POST", "/v2/checkout/orders/O1/capture"): httpx.Response(201, json={"id": "O1"})})
    with pytest.raises(PayPalError) as problem:
        client.capture_order("O1")
    assert (problem.value.status, problem.value.name) == (422, "CAPTURE_MISSING")
