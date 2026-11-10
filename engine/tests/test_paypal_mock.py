import pytest

from parable.paypal import PayPalError
from parable.paypal_mock import MockPayPal


@pytest.fixture
def mock():
    return MockPayPal(public_base_url="http://parable.test/")


def make_order(mock, custom_id="p_1", amount_cents=2500):
    return mock.create_order(amount_cents, "Bot", custom_id, "http://r", "http://c")


def authorized(mock, custom_id="p_1", amount_cents=2500):
    order = make_order(mock, custom_id, amount_cents)
    mock.approve(order["id"])
    return mock.authorize_order(order["id"])


def failure_name(call, *arguments):
    with pytest.raises(PayPalError) as problem:
        call(*arguments)
    return problem.value.status, problem.value.name


def test_create_order_points_at_the_mock_approve_page(mock):
    order = make_order(mock)
    assert order["id"].startswith("MOCK-ORDER-")
    assert order["status"] == "CREATED"
    assert order["approve_url"] == f"http://parable.test/paypal/mock-approve?order={order['id']}"


def test_create_order_is_idempotent_per_custom_id(mock):
    assert make_order(mock, "p_1") == make_order(mock, "p_1")
    assert make_order(mock, "p_2")["id"] != make_order(mock, "p_1")["id"]


def test_create_order_rejects_non_positive_amounts(mock):
    assert failure_name(make_order, mock, "p_x", 0)[1] == "INVALID_PARAMETER_VALUE"


def test_get_order_reports_amount_and_status(mock):
    order = make_order(mock, "p_1", 1999)
    fetched = mock.get_order(order["id"])
    assert fetched["status"] == "CREATED"
    assert fetched["purchase_units"][0]["amount"] == {"currency_code": "USD", "value": "19.99"}
    assert fetched["purchase_units"][0]["custom_id"] == "p_1"
    mock.approve(order["id"])
    assert mock.get_order(order["id"])["status"] == "APPROVED"


def test_authorize_requires_approval(mock):
    order = make_order(mock)
    assert failure_name(mock.authorize_order, order["id"]) == (422, "ORDER_NOT_APPROVED")


def test_authorize_returns_authorization_and_payer(mock):
    order = make_order(mock)
    mock.approve(order["id"], payer_email="buyer@example.com", payer_id="BUYER1")
    result = mock.authorize_order(order["id"])
    assert result["authorization_id"].startswith("MOCK-AUTH-")
    assert result["status"] == "CREATED"
    assert result["payer_email"] == "buyer@example.com"
    assert result["payer_id"] == "BUYER1"
    assert result["expiration_time"].endswith("Z")
    assert mock.get_order(order["id"])["status"] == "COMPLETED"


def test_authorize_twice_is_rejected(mock):
    order = make_order(mock)
    mock.approve(order["id"])
    mock.authorize_order(order["id"])
    assert failure_name(mock.authorize_order, order["id"]) == (422, "ORDER_ALREADY_AUTHORIZED")


def test_unknown_order_is_not_found(mock):
    assert failure_name(mock.authorize_order, "NOPE") == (404, "RESOURCE_NOT_FOUND")
    assert failure_name(mock.approve, "NOPE") == (404, "RESOURCE_NOT_FOUND")
    assert failure_name(mock.get_order, "NOPE") == (404, "RESOURCE_NOT_FOUND")


def test_approve_is_idempotent_but_not_after_authorization(mock):
    order = make_order(mock)
    mock.approve(order["id"])
    mock.approve(order["id"])
    mock.authorize_order(order["id"])
    assert failure_name(mock.approve, order["id"])[1] == "ORDER_NOT_APPROVABLE"


def test_capture_completes_authorization(mock):
    auth = authorized(mock)["authorization_id"]
    capture = mock.capture_authorization(auth, 2500, "p_1")
    assert capture["capture_id"].startswith("MOCK-CAPTURE-")
    assert capture["status"] == "COMPLETED"
    assert mock.get_authorization(auth)["status"] == "CAPTURED"


def test_double_capture_is_rejected(mock):
    auth = authorized(mock)["authorization_id"]
    mock.capture_authorization(auth, 2500, "p_1")
    assert failure_name(mock.capture_authorization, auth, 2500, "p_1") == (422, "AUTHORIZATION_ALREADY_CAPTURED")


def test_void_then_capture_or_void_is_rejected(mock):
    auth = authorized(mock)["authorization_id"]
    assert mock.void_authorization(auth) == {"status": "VOIDED"}
    assert mock.get_authorization(auth)["status"] == "VOIDED"
    assert failure_name(mock.capture_authorization, auth, 2500, "p_1") == (422, "AUTHORIZATION_VOIDED")
    assert failure_name(mock.void_authorization, auth) == (422, "AUTHORIZATION_ALREADY_VOIDED")


def test_void_after_capture_is_rejected(mock):
    auth = authorized(mock)["authorization_id"]
    mock.capture_authorization(auth, 2500, "p_1")
    assert failure_name(mock.void_authorization, auth) == (422, "AUTHORIZATION_ALREADY_CAPTURED")


def test_capture_cannot_exceed_the_held_amount(mock):
    auth = authorized(mock, amount_cents=1000)["authorization_id"]
    assert failure_name(mock.capture_authorization, auth, 1001, "p_1")[1] == "CAPTURE_AMOUNT_EXCEEDS_AUTHORIZATION"
    assert failure_name(mock.capture_authorization, auth, 0, "p_1")[1] == "INVALID_PARAMETER_VALUE"
    assert mock.get_authorization(auth)["status"] == "CREATED"


def test_partial_capture_keeps_remaining_balance(mock):
    auth = authorized(mock, amount_cents=1000)["authorization_id"]
    mock.capture_authorization(auth, 400, "p_1", final=False)
    assert mock.get_authorization(auth)["status"] == "PARTIALLY_CAPTURED"
    assert failure_name(mock.capture_authorization, auth, 700, "p_1")[1] == "CAPTURE_AMOUNT_EXCEEDS_AUTHORIZATION"
    mock.capture_authorization(auth, 600, "p_1")
    assert mock.get_authorization(auth)["status"] == "CAPTURED"


def test_get_authorization_shape(mock):
    auth = authorized(mock, "p_9", 4200)["authorization_id"]
    held = mock.get_authorization(auth)
    assert held["amount"] == {"currency_code": "USD", "value": "42.00"}
    assert held["invoice_id"] == "p_9"


def test_unknown_authorization_is_not_found(mock):
    assert failure_name(mock.capture_authorization, "NOPE", 100, "p") == (404, "RESOURCE_NOT_FOUND")
    assert failure_name(mock.void_authorization, "NOPE") == (404, "RESOURCE_NOT_FOUND")
    assert failure_name(mock.get_authorization, "NOPE") == (404, "RESOURCE_NOT_FOUND")


def test_authorization_from_before_a_restart_can_still_settle(mock):
    assert mock.capture_authorization("MOCK-AUTH-0007", 2500, "p_1")["status"] == "COMPLETED"
    assert failure_name(mock.capture_authorization, "MOCK-AUTH-0007", 2500, "p_1")[1] == "AUTHORIZATION_ALREADY_CAPTURED"


def test_payout_is_idempotent_per_batch_id(mock):
    first = mock.create_payout("p_1-payout", "seller@example.com", 2250, "Bot sale")
    second = mock.create_payout("p_1-payout", "seller@example.com", 2250, "Bot sale")
    assert first == second
    assert first["payout_batch_id"].startswith("MOCK-PAYOUT-")
    assert first["batch_status"] == "SUCCESS"
    other = mock.create_payout("p_2-payout", "seller@example.com", 100, "Bot sale")
    assert other["payout_batch_id"] != first["payout_batch_id"]


def test_get_payout_by_batch_or_payout_id(mock):
    created = mock.create_payout("p_1-payout", "seller@example.com", 2250, "Bot sale")
    by_sender = mock.get_payout("p_1-payout")
    by_paypal = mock.get_payout(created["payout_batch_id"])
    assert by_sender == by_paypal
    assert by_sender["batch_status"] == "SUCCESS"
    assert by_sender["items"][0]["payout_item"]["amount"] == {"value": "22.50", "currency": "USD"}
    assert by_sender["items"][0]["payout_item"]["receiver"] == "seller@example.com"


def test_payout_validation_and_missing_batch(mock):
    assert failure_name(mock.create_payout, "b", "a@b.c", 0, "n")[1] == "INVALID_PARAMETER_VALUE"
    assert failure_name(mock.get_payout, "missing") == (404, "RESOURCE_NOT_FOUND")


def test_webhooks_always_verify_and_login_returns_demo_seller(mock):
    assert mock.verify_webhook({}, {}, "any") is True
    assert mock.oauth_authorize_url("st", "http://cb") == "http://parable.test/paypal/mock-login?state=st"
    info = mock.userinfo(mock.exchange_code("code"))
    assert info["payer_id"] and info["email"] and info["verified"] is True
