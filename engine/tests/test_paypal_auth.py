from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from paypal_support import Recorder, body_of, build, token_response
from parable.paypal import PayPalClient, PayPalError, get_paypal, is_mock, set_paypal
from parable.paypal_mock import MockPayPal


def test_token_request_uses_basic_auth_and_client_credentials():
    client, recorder = build({})
    assert client.token() == "tok-1"
    request = recorder.sent("POST", "/v1/oauth2/token")[0]
    assert request.headers["authorization"].startswith("Basic ")
    assert parse_qs(request.content.decode()) == {"grant_type": ["client_credentials"]}
    assert request.url.host == "api-m.sandbox.paypal.com"


def test_token_is_cached_until_it_expires():
    now = [1000.0]
    client, recorder = build({}, clock=lambda: now[0])
    client.token()
    client.token()
    assert len(recorder.sent("POST", "/v1/oauth2/token")) == 1
    now[0] += 32400 - 61
    client.token()
    assert len(recorder.sent("POST", "/v1/oauth2/token")) == 1
    now[0] += 2
    client.token()
    assert len(recorder.sent("POST", "/v1/oauth2/token")) == 2


def test_live_environment_uses_live_hosts():
    http = httpx.Client(transport=httpx.MockTransport(Recorder({("POST", "/v1/oauth2/token"): token_response()})))
    client = PayPalClient(client_id="cid", client_secret="secret", env="live", http=http)
    assert client.base_url == "https://api-m.paypal.com"
    assert client.oauth_authorize_url("s", "https://x/cb").startswith("https://www.paypal.com/signin/authorize?")


WEBHOOK_HEADERS = {
    "PAYPAL-TRANSMISSION-ID": "t-1",
    "PAYPAL-TRANSMISSION-TIME": "2026-11-10T10:00:00Z",
    "PAYPAL-CERT-URL": "https://api.paypal.com/cert.pem",
    "PAYPAL-AUTH-ALGO": "SHA256withRSA",
    "PAYPAL-TRANSMISSION-SIG": "sig",
}
VERIFY_ROUTE = ("POST", "/v1/notifications/verify-webhook-signature")


def test_verify_webhook_posts_all_fields_and_accepts_success():
    reply = httpx.Response(200, json={"verification_status": "SUCCESS"})
    client, recorder = build({VERIFY_ROUTE: reply})
    event = {"id": "WH-1", "event_type": "PAYMENT.CAPTURE.COMPLETED"}
    assert client.verify_webhook(WEBHOOK_HEADERS, event, "WEBHOOK-ID") is True
    body = body_of(recorder.sent(*VERIFY_ROUTE)[0])
    assert body == {
        "transmission_id": "t-1",
        "transmission_time": "2026-11-10T10:00:00Z",
        "cert_url": "https://api.paypal.com/cert.pem",
        "auth_algo": "SHA256withRSA",
        "transmission_sig": "sig",
        "webhook_id": "WEBHOOK-ID",
        "webhook_event": event,
    }


def test_verify_webhook_reads_headers_case_insensitively():
    reply = httpx.Response(200, json={"verification_status": "SUCCESS"})
    client, _ = build({VERIFY_ROUTE: reply})
    lowered = {key.lower(): value for key, value in WEBHOOK_HEADERS.items()}
    assert client.verify_webhook(lowered, {}, "WEBHOOK-ID") is True


def test_verify_webhook_rejects_failure_missing_headers_and_api_errors():
    client, recorder = build({VERIFY_ROUTE: httpx.Response(200, json={"verification_status": "FAILURE"})})
    assert client.verify_webhook(WEBHOOK_HEADERS, {}, "WEBHOOK-ID") is False
    assert client.verify_webhook({}, {}, "WEBHOOK-ID") is False
    assert client.verify_webhook(WEBHOOK_HEADERS, {}, "") is False
    assert len(recorder.sent(*VERIFY_ROUTE)) == 1
    broken, _ = build({VERIFY_ROUTE: httpx.Response(500, json={"name": "INTERNAL_SERVICE_ERROR"})})
    assert broken.verify_webhook(WEBHOOK_HEADERS, {}, "WEBHOOK-ID") is False


def test_oauth_authorize_url_encodes_parameters():
    client, _ = build({})
    url = client.oauth_authorize_url("state-1", "https://parable.example/paypal/callback")
    parsed = urlparse(url)
    assert (parsed.scheme, parsed.netloc, parsed.path) == ("https", "www.sandbox.paypal.com", "/signin/authorize")
    query = parse_qs(parsed.query)
    assert query["client_id"] == ["cid"]
    assert query["response_type"] == ["code"]
    assert query["state"] == ["state-1"]
    assert query["redirect_uri"] == ["https://parable.example/paypal/callback"]
    assert query["scope"] == ["openid profile email https://uri.paypal.com/services/paypalattributes"]
    assert "%20" in parsed.query and "+" not in parsed.query


def test_exchange_code_posts_authorization_code_grant():
    reply = httpx.Response(200, json={"access_token": "user-tok", "expires_in": 100})
    client, recorder = build({("POST", "/v1/oauth2/token"): reply})
    assert client.exchange_code("CODE1") == "user-tok"
    request = recorder.sent("POST", "/v1/oauth2/token")[0]
    assert parse_qs(request.content.decode()) == {"grant_type": ["authorization_code"], "code": ["CODE1"]}
    assert request.headers["authorization"].startswith("Basic ")


def test_userinfo_prefers_primary_email_and_payer_id():
    info = {
        "payer_id": "PAYER1",
        "user_id": "https://paypal/u/ignored",
        "name": "Ada Lovelace",
        "emails": [{"value": "other@example.com"}, {"value": "ada@example.com", "primary": True}],
        "verified_account": "true",
    }
    client, recorder = build({("GET", "/v1/identity/oauth2/userinfo"): httpx.Response(200, json=info)})
    assert client.userinfo("user-tok") == {
        "payer_id": "PAYER1",
        "name": "Ada Lovelace",
        "email": "ada@example.com",
        "verified": True,
    }
    request = recorder.sent("GET", "/v1/identity/oauth2/userinfo")[0]
    assert request.url.params["schema"] == "paypalv1.1"
    assert request.headers["authorization"] == "Bearer user-tok"
    assert len(recorder.sent("POST", "/v1/oauth2/token")) == 0


def test_userinfo_falls_back_to_user_id_and_unverified():
    info = {"user_id": "UID9", "given_name": "Grace", "family_name": "Hopper", "emails": [{"value": "g@example.com"}]}
    client, _ = build({("GET", "/v1/identity/oauth2/userinfo"): httpx.Response(200, json=info)})
    assert client.userinfo("user-tok") == {
        "payer_id": "UID9",
        "name": "Grace Hopper",
        "email": "g@example.com",
        "verified": False,
    }


def test_error_prefers_detail_issue_over_name():
    payload = {
        "name": "UNPROCESSABLE_ENTITY",
        "message": "The requested action could not be performed.",
        "details": [{"issue": "AUTHORIZATION_ALREADY_CAPTURED", "description": "Authorization has been captured."}],
    }
    route = ("POST", "/v2/payments/authorizations/AUTH-1/capture")
    client, _ = build({route: httpx.Response(422, json=payload)})
    with pytest.raises(PayPalError) as problem:
        client.capture_authorization("AUTH-1", 100, "p")
    assert problem.value.status == 422
    assert problem.value.name == "AUTHORIZATION_ALREADY_CAPTURED"
    assert problem.value.detail == "Authorization has been captured."


@pytest.mark.parametrize(
    "response, expected_name, expected_detail",
    [
        (httpx.Response(400, json={"name": "INVALID_REQUEST", "message": "bad"}), "INVALID_REQUEST", "bad"),
        (httpx.Response(400, json={"name": "INVALID_REQUEST", "details": []}), "INVALID_REQUEST", ""),
        (httpx.Response(502, text="<html>gateway</html>"), "HTTP_502", ""),
        (httpx.Response(500, json=["unexpected"]), "HTTP_500", ""),
        (httpx.Response(401, json={"error": "invalid_client", "error_description": "no"}), "invalid_client", "no"),
    ],
)
def test_error_mapping_is_robust(response, expected_name, expected_detail):
    client, _ = build({("GET", "/v2/checkout/orders/O"): response})
    with pytest.raises(PayPalError) as problem:
        client.get_order("O")
    assert problem.value.name == expected_name
    assert problem.value.detail == expected_detail
    assert problem.value.status == response.status_code


def test_error_message_never_contains_credentials():
    bad_token = httpx.Response(401, json={"error": "invalid_client", "error_description": "Client Authentication failed"})
    http = httpx.Client(transport=httpx.MockTransport(Recorder({("POST", "/v1/oauth2/token"): bad_token})))
    client = PayPalClient(client_id="cid", client_secret="super-secret", env="sandbox", http=http)
    with pytest.raises(PayPalError) as problem:
        client.token()
    assert "super-secret" not in str(problem.value)


def test_network_failure_becomes_paypal_error():
    def explode(request):
        raise httpx.ConnectError("boom")

    http = httpx.Client(transport=httpx.MockTransport(explode))
    client = PayPalClient(client_id="cid", client_secret="secret", env="sandbox", http=http)
    with pytest.raises(PayPalError) as problem:
        client.token()
    assert problem.value.name == "NETWORK_ERROR"
    assert problem.value.status == 502


def test_unauthorized_response_refreshes_token_once():
    tokens = iter(["tok-1", "tok-2"])
    calls = []

    def order(request):
        calls.append(request.headers["authorization"])
        if len(calls) == 1:
            return httpx.Response(401, json={"name": "AUTHENTICATION_FAILURE"})
        return httpx.Response(200, json={"id": "O", "status": "CREATED"})

    routes = {("GET", "/v2/checkout/orders/O"): order, ("POST", "/v1/oauth2/token"): lambda r: token_response(token=next(tokens))}
    client, recorder = build(routes)
    assert client.get_order("O")["id"] == "O"
    assert calls == ["Bearer tok-1", "Bearer tok-2"]
    assert len(recorder.sent("POST", "/v1/oauth2/token")) == 2


def test_persistent_unauthorized_raises_after_one_retry():
    route = ("GET", "/v2/checkout/orders/O")
    client, recorder = build({route: httpx.Response(401, json={"name": "AUTHENTICATION_FAILURE"})})
    with pytest.raises(PayPalError) as problem:
        client.get_order("O")
    assert problem.value.status == 401
    assert len(recorder.sent(*route)) == 2


def test_token_response_without_access_token_is_rejected():
    http = httpx.Client(transport=httpx.MockTransport(Recorder({("POST", "/v1/oauth2/token"): httpx.Response(200, json={})})))
    client = PayPalClient(client_id="cid", client_secret="secret", env="sandbox", http=http)
    with pytest.raises(PayPalError) as problem:
        client.token()
    assert problem.value.name == "UNEXPECTED_RESPONSE"


def test_get_and_set_paypal_singleton(monkeypatch):
    set_paypal(None)
    monkeypatch.setattr("parable.paypal.paypal_mocked", lambda: True)
    first = get_paypal()
    assert isinstance(first, MockPayPal) and get_paypal() is first and is_mock()
    replacement = MockPayPal(public_base_url="http://x")
    set_paypal(replacement)
    assert get_paypal() is replacement
    set_paypal(None)


def test_get_paypal_builds_real_client_when_keys_are_present(monkeypatch):
    set_paypal(None)
    monkeypatch.setattr("parable.paypal.paypal_mocked", lambda: False)
    try:
        assert isinstance(get_paypal(), PayPalClient)
        assert not is_mock()
    finally:
        set_paypal(None)
