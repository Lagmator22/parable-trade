
import httpx
import pytest

from paypal_support import body_of, build
from parable.paypal import PayPalError, cents_to_value, value_to_cents


def test_amount_conversion_round_trip():
    assert cents_to_value(1234) == "12.34"
    assert cents_to_value(5) == "0.05"
    assert cents_to_value(2500) == "25.00"
    assert cents_to_value(0) == "0.00"
    assert value_to_cents("12.34") == 1234
    assert value_to_cents("12.3") == 1230
    assert value_to_cents("12") == 1200
    assert value_to_cents("0.05") == 5


def test_amount_conversion_rejects_bad_input():
    with pytest.raises(ValueError):
        cents_to_value(-1)
    for bad in ("abc", "", "NaN", "Infinity"):
        with pytest.raises(ValueError):
            value_to_cents(bad)


ORDER_RESPONSE = {
    "id": "ORDER-1",
    "status": "PAYER_ACTION_REQUIRED",
    "links": [
        {"rel": "self", "href": "https://api/self"},
        {"rel": "payer-action", "href": "https://www.sandbox.paypal.com/checkoutnow?token=ORDER-1"},
    ],
}


def create_order(client, **overrides):
    arguments = {
        "amount_cents": 2500,
        "description": "Momentum bot",
        "custom_id": "p_abc",
        "return_url": "https://parable/paypal/return",
        "cancel_url": "https://parable/paypal/cancel",
    }
    return client.create_order(**{**arguments, **overrides})


def test_create_order_builds_authorize_request():
    client, recorder = build({("POST", "/v2/checkout/orders"): httpx.Response(201, json=ORDER_RESPONSE)})
    created = create_order(client)
    assert created == {
        "id": "ORDER-1",
        "status": "PAYER_ACTION_REQUIRED",
        "approve_url": "https://www.sandbox.paypal.com/checkoutnow?token=ORDER-1",
    }
    request = recorder.sent("POST", "/v2/checkout/orders")[0]
    assert request.headers["authorization"] == "Bearer tok-1"
    assert request.headers["paypal-request-id"] == "p_abc:create"
    assert request.headers["prefer"] == "return=representation"
    body = body_of(request)
    unit = body["purchase_units"][0]
    assert body["intent"] == "AUTHORIZE"
    assert unit["amount"] == {"currency_code": "USD", "value": "25.00"}
    assert unit["custom_id"] == "p_abc" and unit["invoice_id"] == "p_abc"
    context = body["payment_source"]["paypal"]["experience_context"]
    assert context["brand_name"] == "Parable"
    assert context["user_action"] == "PAY_NOW"
    assert context["shipping_preference"] == "NO_SHIPPING"
    assert context["return_url"] == "https://parable/paypal/return"
    assert context["cancel_url"] == "https://parable/paypal/cancel"


def test_create_order_truncates_description_and_formats_small_amounts():
    client, recorder = build({("POST", "/v2/checkout/orders"): httpx.Response(201, json=ORDER_RESPONSE)})
    create_order(client, description="x" * 300, amount_cents=105)
    unit = body_of(recorder.sent("POST", "/v2/checkout/orders")[0])["purchase_units"][0]
    assert len(unit["description"]) == 127
    assert unit["amount"]["value"] == "1.05"


def test_create_order_accepts_approve_link_and_rejects_missing_link():
    legacy = {"id": "O2", "status": "CREATED", "links": [{"rel": "approve", "href": "https://paypal/approve"}]}
    client, _ = build({("POST", "/v2/checkout/orders"): httpx.Response(201, json=legacy)})
    assert create_order(client)["approve_url"] == "https://paypal/approve"
    bare = {"id": "O3", "status": "CREATED", "links": []}
    client, _ = build({("POST", "/v2/checkout/orders"): httpx.Response(201, json=bare)})
    with pytest.raises(PayPalError) as problem:
        create_order(client)
    assert problem.value.name == "UNEXPECTED_RESPONSE"


def authorized_order(payer=None, source=None):
    authorization = {"id": "AUTH-1", "status": "CREATED", "expiration_time": "2026-12-09T00:00:00Z"}
    order = {"id": "ORDER-1", "purchase_units": [{"payments": {"authorizations": [authorization]}}]}
    if payer:
        order["payer"] = payer
    if source:
        order["payment_source"] = {"paypal": source}
    return order


def test_authorize_order_reads_payer_block():
    order = authorized_order(payer={"email_address": "buyer@example.com", "payer_id": "PAYER9"})
    client, recorder = build({("POST", "/v2/checkout/orders/ORDER-1/authorize"): httpx.Response(201, json=order)})
    result = client.authorize_order("ORDER-1")
    assert result == {
        "authorization_id": "AUTH-1",
        "status": "CREATED",
        "expiration_time": "2026-12-09T00:00:00Z",
        "payer_email": "buyer@example.com",
        "payer_id": "PAYER9",
    }
    request = recorder.sent("POST", "/v2/checkout/orders/ORDER-1/authorize")[0]
    assert request.headers["paypal-request-id"] == "ORDER-1:authorize"
    assert request.headers["authorization"] == "Bearer tok-1"


def test_authorize_order_reads_payment_source_block():
    order = authorized_order(source={"email_address": "src@example.com", "account_id": "ACC7"})
    client, _ = build({("POST", "/v2/checkout/orders/ORDER-1/authorize"): httpx.Response(201, json=order)})
    result = client.authorize_order("ORDER-1")
    assert (result["payer_email"], result["payer_id"]) == ("src@example.com", "ACC7")


def test_authorize_order_without_payer_still_returns_authorization():
    client, _ = build({("POST", "/v2/checkout/orders/ORDER-1/authorize"): httpx.Response(201, json=authorized_order())})
    result = client.authorize_order("ORDER-1")
    assert (result["payer_email"], result["payer_id"]) == ("", "")


def test_authorize_order_without_authorization_raises():
    empty = {"id": "ORDER-1", "purchase_units": [{"payments": {}}]}
    client, _ = build({("POST", "/v2/checkout/orders/ORDER-1/authorize"): httpx.Response(201, json=empty)})
    with pytest.raises(PayPalError) as problem:
        client.authorize_order("ORDER-1")
    assert problem.value.name == "AUTHORIZATION_MISSING"


def test_order_ids_are_path_escaped():
    client, recorder = build({})
    with pytest.raises(PayPalError):
        client.get_order("../evil")
    assert recorder.requests[-1].url.raw_path.decode() == "/v2/checkout/orders/..%2Fevil"


def test_capture_authorization_request_and_response():
    route = ("POST", "/v2/payments/authorizations/AUTH-1/capture")
    client, recorder = build({route: httpx.Response(201, json={"id": "CAP-1", "status": "COMPLETED"})})
    assert client.capture_authorization("AUTH-1", 2500, "p_abc") == {"capture_id": "CAP-1", "status": "COMPLETED"}
    request = recorder.sent(*route)[0]
    assert body_of(request) == {
        "amount": {"currency_code": "USD", "value": "25.00"},
        "invoice_id": "p_abc",
        "final_capture": True,
    }
    assert request.headers["paypal-request-id"].startswith("AUTH-1:capture")


def test_partial_capture_sets_final_capture_false():
    route = ("POST", "/v2/payments/authorizations/AUTH-1/capture")
    client, recorder = build({route: httpx.Response(201, json={"id": "CAP-2", "status": "COMPLETED"})})
    client.capture_authorization("AUTH-1", 100, "p_abc", final=False)
    assert body_of(recorder.sent(*route)[0])["final_capture"] is False


def test_void_authorization_handles_empty_204():
    route = ("POST", "/v2/payments/authorizations/AUTH-1/void")
    client, recorder = build({route: httpx.Response(204)})
    assert client.void_authorization("AUTH-1") == {"status": "VOIDED"}
    assert recorder.sent(*route)[0].headers["authorization"] == "Bearer tok-1"


def test_get_authorization_and_get_order_return_payload():
    routes = {
        ("GET", "/v2/payments/authorizations/AUTH-1"): httpx.Response(200, json={"id": "AUTH-1", "status": "CREATED"}),
        ("GET", "/v2/checkout/orders/ORDER-1"): httpx.Response(200, json={"id": "ORDER-1", "status": "APPROVED"}),
    }
    client, _ = build(routes)
    assert client.get_authorization("AUTH-1")["status"] == "CREATED"
    assert client.get_order("ORDER-1")["status"] == "APPROVED"


def test_create_payout_body_and_response():
    reply = {"batch_header": {"payout_batch_id": "PB-1", "batch_status": "PENDING"}}
    client, recorder = build({("POST", "/v1/payments/payouts"): httpx.Response(201, json=reply)})
    result = client.create_payout("p_abc-payout", "seller@example.com", 2250, "Bot sale")
    assert result == {"payout_batch_id": "PB-1", "batch_status": "PENDING"}
    request = recorder.sent("POST", "/v1/payments/payouts")[0]
    assert request.headers["paypal-request-id"] == "p_abc-payout"
    body = body_of(request)
    assert body["sender_batch_header"]["sender_batch_id"] == "p_abc-payout"
    assert body["sender_batch_header"]["email_subject"]
    assert body["sender_batch_header"]["email_message"] == "Bot sale"
    item = body["items"][0]
    assert item["recipient_type"] == "EMAIL"
    assert item["receiver"] == "seller@example.com"
    assert item["amount"] == {"value": "22.50", "currency": "USD"}
    assert item["sender_item_id"]


def test_get_payout_returns_status_and_items():
    reply = {"batch_header": {"batch_status": "SUCCESS"}, "items": [{"payout_item_id": "I1"}]}
    client, _ = build({("GET", "/v1/payments/payouts/PB-1"): httpx.Response(200, json=reply)})
    assert client.get_payout("PB-1") == {"batch_status": "SUCCESS", "items": [{"payout_item_id": "I1"}]}
