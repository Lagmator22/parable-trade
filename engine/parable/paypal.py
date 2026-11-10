import threading
import time
from urllib.parse import quote, urlencode

import httpx

from parable.config import get_settings, paypal_mocked
from parable.paypal_core import (
    PayPalError,
    approve_url,
    cents_to_value,
    error_from_payload,
    first_authorization,
    money,
    parse_userinfo,
    payer_identity,
    unexpected_response,
    value_to_cents,
)
from parable.paypal_mock import MockPayPal

__all__ = [
    "MockPayPal",
    "PayPalClient",
    "PayPalError",
    "cents_to_value",
    "get_paypal",
    "is_mock",
    "set_paypal",
    "value_to_cents",
]

API_URLS = {"sandbox": "https://api-m.sandbox.paypal.com", "live": "https://api-m.paypal.com"}
LOGIN_URLS = {"sandbox": "https://www.sandbox.paypal.com", "live": "https://www.paypal.com"}
LOGIN_SCOPE = "openid profile email https://uri.paypal.com/services/paypalattributes"
BRAND_NAME = "Parable"
TOKEN_SAFETY_MARGIN_S = 60
REQUEST_TIMEOUT_S = 20.0
WEBHOOK_HEADERS = {
    "transmission_id": "paypal-transmission-id",
    "transmission_time": "paypal-transmission-time",
    "cert_url": "paypal-cert-url",
    "auth_algo": "paypal-auth-algo",
    "transmission_sig": "paypal-transmission-sig",
}


def segment(value: str) -> str:
    return quote(str(value), safe="")


def json_or_none(response: httpx.Response):
    try:
        return response.json()
    except ValueError:
        return None


class PayPalClient:
    def __init__(self, client_id=None, client_secret=None, env=None, http=None, clock=time.time):
        settings = get_settings()
        self.client_id = settings.paypal_client_id if client_id is None else client_id
        self.client_secret = settings.paypal_client_secret if client_secret is None else client_secret
        self.env = "live" if (env or settings.paypal_env) == "live" else "sandbox"
        self.base_url = API_URLS[self.env]
        self.login_url = LOGIN_URLS[self.env]
        self._http = http or httpx.Client(timeout=REQUEST_TIMEOUT_S)
        self._clock = clock
        self._lock = threading.Lock()
        self._token = ""
        self._token_expires_at = 0.0

    def token(self) -> str:
        with self._lock:
            if self._token and self._clock() < self._token_expires_at:
                return self._token
            payload = self._send(
                "POST",
                "/v1/oauth2/token",
                data={"grant_type": "client_credentials"},
                auth=(self.client_id, self.client_secret),
            )
            if not payload.get("access_token"):
                raise unexpected_response("access_token")
            lifetime = int(payload.get("expires_in") or 0)
            self._token = payload["access_token"]
            self._token_expires_at = self._clock() + lifetime - TOKEN_SAFETY_MARGIN_S
            return self._token

    def _forget_token(self) -> None:
        with self._lock:
            self._token = ""

    def _send(self, method: str, path: str, **options) -> dict:
        try:
            response = self._http.request(method, self.base_url + path, **options)
        except httpx.HTTPError as error:
            raise PayPalError(502, "NETWORK_ERROR", type(error).__name__) from error
        if response.status_code >= 400:
            raise error_from_payload(response.status_code, json_or_none(response))
        payload = json_or_none(response) if response.content else {}
        return payload if isinstance(payload, dict) else {}

    def _call_once(self, method, path, bearer, json, params, request_id, representation) -> dict:
        headers = {"Authorization": f"Bearer {bearer or self.token()}"}
        if request_id:
            headers["PayPal-Request-Id"] = request_id
        if representation:
            headers["Prefer"] = "return=representation"
        return self._send(method, path, headers=headers, json=json, params=params)

    def _call(self, method, path, *, json=None, params=None, request_id=None, representation=False, bearer=None):
        arguments = (method, path, bearer, json, params, request_id, representation)
        try:
            return self._call_once(*arguments)
        except PayPalError as error:
            if error.status != 401 or bearer:
                raise
            self._forget_token()
            return self._call_once(*arguments)

    def create_order(self, amount_cents, description, custom_id, return_url, cancel_url) -> dict:
        body = {
            "intent": "AUTHORIZE",
            "purchase_units": [
                {
                    "reference_id": custom_id,
                    "custom_id": custom_id,
                    "invoice_id": custom_id,
                    "description": description[:127],
                    "amount": money(amount_cents),
                }
            ],
            "payment_source": {
                "paypal": {
                    "experience_context": {
                        "brand_name": BRAND_NAME,
                        "user_action": "PAY_NOW",
                        "shipping_preference": "NO_SHIPPING",
                        "return_url": return_url,
                        "cancel_url": cancel_url,
                    }
                }
            },
        }
        order = self._call(
            "POST", "/v2/checkout/orders", json=body, request_id=f"{custom_id}:create", representation=True
        )
        if not order.get("id"):
            raise unexpected_response("id")
        url = approve_url(order)
        if not url:
            raise unexpected_response("approve link")
        return {"id": order["id"], "status": order.get("status", ""), "approve_url": url}

    def get_order(self, order_id) -> dict:
        return self._call("GET", f"/v2/checkout/orders/{segment(order_id)}")

    def authorize_order(self, order_id) -> dict:
        order = self._call(
            "POST",
            f"/v2/checkout/orders/{segment(order_id)}/authorize",
            json={},
            request_id=f"{order_id}:authorize",
            representation=True,
        )
        authorization = first_authorization(order)
        if not authorization or not authorization.get("id"):
            raise PayPalError(422, "AUTHORIZATION_MISSING", "order response holds no authorization")
        email, payer_id = payer_identity(order)
        return {
            "authorization_id": authorization["id"],
            "status": authorization.get("status", ""),
            "expiration_time": authorization.get("expiration_time", ""),
            "payer_email": email,
            "payer_id": payer_id,
        }

    def capture_authorization(self, auth_id, amount_cents, invoice_id, final=True) -> dict:
        body = {"amount": money(amount_cents), "invoice_id": invoice_id, "final_capture": final}
        capture = self._call(
            "POST",
            f"/v2/payments/authorizations/{segment(auth_id)}/capture",
            json=body,
            request_id=f"{auth_id}:capture:{amount_cents}",
        )
        if not capture.get("id"):
            raise unexpected_response("id")
        return {"capture_id": capture["id"], "status": capture.get("status", "")}

    def void_authorization(self, auth_id) -> dict:
        self._call("POST", f"/v2/payments/authorizations/{segment(auth_id)}/void", request_id=f"{auth_id}:void")
        return {"status": "VOIDED"}

    def get_authorization(self, auth_id) -> dict:
        return self._call("GET", f"/v2/payments/authorizations/{segment(auth_id)}")

    def create_payout(self, batch_id, receiver_email, amount_cents, note) -> dict:
        body = {
            "sender_batch_header": {
                "sender_batch_id": batch_id,
                "email_subject": "Your Parable bot sale was paid out",
                "email_message": note,
            },
            "items": [
                {
                    "recipient_type": "EMAIL",
                    "amount": {"value": cents_to_value(amount_cents), "currency": "USD"},
                    "receiver": receiver_email,
                    "note": note,
                    "sender_item_id": batch_id,
                }
            ],
        }
        response = self._call("POST", "/v1/payments/payouts", json=body, request_id=batch_id)
        header = response.get("batch_header") or {}
        if not header.get("payout_batch_id"):
            raise unexpected_response("payout_batch_id")
        return {"payout_batch_id": header["payout_batch_id"], "batch_status": header.get("batch_status", "")}

    def get_payout(self, batch_id) -> dict:
        response = self._call("GET", f"/v1/payments/payouts/{segment(batch_id)}")
        header = response.get("batch_header") or {}
        return {"batch_status": header.get("batch_status", ""), "items": response.get("items") or []}

    def verify_webhook(self, headers, body, webhook_id) -> bool:
        lowered = {str(key).lower(): value for key, value in headers.items()}
        fields = {field: lowered.get(header) for field, header in WEBHOOK_HEADERS.items()}
        if not webhook_id or not all(fields.values()):
            return False
        payload = {**fields, "webhook_id": webhook_id, "webhook_event": body}
        try:
            result = self._call("POST", "/v1/notifications/verify-webhook-signature", json=payload)
        except PayPalError:
            return False
        return result.get("verification_status") == "SUCCESS"

    def oauth_authorize_url(self, state, redirect_uri) -> str:
        query = urlencode(
            {
                "flowEntry": "static",
                "client_id": self.client_id,
                "response_type": "code",
                "scope": LOGIN_SCOPE,
                "redirect_uri": redirect_uri,
                "state": state,
            },
            quote_via=quote,
        )
        return f"{self.login_url}/signin/authorize?{query}"

    def exchange_code(self, code) -> str:
        payload = self._send(
            "POST",
            "/v1/oauth2/token",
            data={"grant_type": "authorization_code", "code": code},
            auth=(self.client_id, self.client_secret),
        )
        if not payload.get("access_token"):
            raise unexpected_response("access_token")
        return payload["access_token"]

    def userinfo(self, user_token) -> dict:
        info = self._call(
            "GET", "/v1/identity/oauth2/userinfo", params={"schema": "paypalv1.1"}, bearer=user_token
        )
        return parse_userinfo(info)


_instance = None
_instance_lock = threading.Lock()


def get_paypal() -> PayPalClient | MockPayPal:
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = MockPayPal() if paypal_mocked() else PayPalClient()
        return _instance


def set_paypal(client: PayPalClient | MockPayPal | None) -> None:
    global _instance
    with _instance_lock:
        _instance = client


def is_mock() -> bool:
    return isinstance(get_paypal(), MockPayPal)
