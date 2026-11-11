from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from urllib.parse import quote, urlparse

import httpx

CURRENCY = "USD"
ERROR_DETAIL_LIMIT = 300


class PayPalError(Exception):
    def __init__(self, status: int, name: str, detail: str = ""):
        message = f"{status} {name}: {detail}" if detail else f"{status} {name}"
        super().__init__(message)
        self.status = status
        self.name = name
        self.detail = detail


def cents_to_value(cents: int) -> str:
    if cents < 0:
        raise ValueError("amount must not be negative")
    return f"{cents // 100}.{cents % 100:02d}"


def value_to_cents(value: str) -> int:
    try:
        amount = Decimal(str(value).strip())
    except InvalidOperation as error:
        raise ValueError(f"invalid amount: {value!r}") from error
    if not amount.is_finite():
        raise ValueError(f"invalid amount: {value!r}")
    return int((amount * 100).to_integral_value(ROUND_HALF_UP))


def money(cents: int) -> dict:
    return {"currency_code": CURRENCY, "value": cents_to_value(cents)}


def error_from_payload(status: int, payload) -> PayPalError:
    body = payload if isinstance(payload, dict) else {}
    details = body.get("details")
    first = details[0] if isinstance(details, list) and details and isinstance(details[0], dict) else {}
    name = first.get("issue") or body.get("name") or body.get("error") or f"HTTP_{status}"
    detail = first.get("description") or body.get("message") or body.get("error_description") or ""
    return PayPalError(status, str(name), str(detail)[:ERROR_DETAIL_LIMIT])


def unexpected_response(field: str) -> PayPalError:
    return PayPalError(502, "UNEXPECTED_RESPONSE", f"missing {field}")


def approve_url(order: dict) -> str:
    links = {
        link.get("rel"): link.get("href")
        for link in order.get("links") or []
        if isinstance(link, dict)
    }
    return links.get("payer-action") or links.get("approve") or ""


def first_authorization(order: dict) -> dict | None:
    units = order.get("purchase_units") or []
    payments = (units[0] if units else {}).get("payments") or {}
    authorizations = payments.get("authorizations") or []
    return authorizations[0] if authorizations else None


def payer_identity(order: dict) -> tuple[str, str]:
    payer = order.get("payer") or {}
    source = (order.get("payment_source") or {}).get("paypal") or {}
    email = payer.get("email_address") or source.get("email_address") or ""
    payer_id = payer.get("payer_id") or source.get("account_id") or ""
    return email, payer_id


def parse_userinfo(info: dict) -> dict:
    emails = [entry for entry in info.get("emails") or [] if isinstance(entry, dict)]
    primary = next((entry.get("value") for entry in emails if entry.get("primary")), None)
    listed = emails[0].get("value") if emails else None
    names = [info.get("given_name"), info.get("family_name")]
    return {
        "payer_id": str(info.get("payer_id") or info.get("user_id") or ""),
        "name": info.get("name") or " ".join(part for part in names if part),
        "email": primary or listed or info.get("email") or "",
        "verified": info.get("verified_account") in (True, "true", "True"),
    }


def require_intent(intent: str) -> None:
    if intent not in ("AUTHORIZE", "CAPTURE"):
        raise PayPalError(422, "INVALID_PARAMETER_VALUE", "intent must be AUTHORIZE or CAPTURE")


def parse_capture(order: dict) -> dict:
    units = order.get("purchase_units") or []
    captures = ((units[0] if units else {}).get("payments") or {}).get("captures") or []
    if not captures or not captures[0].get("id"):
        raise PayPalError(422, "CAPTURE_MISSING", "order response holds no capture")
    capture = captures[0]
    email, payer_id = payer_identity(order)
    return {
        "capture_id": capture["id"],
        "status": capture.get("status", ""),
        "amount_cents": value_to_cents((capture.get("amount") or {}).get("value", "0")),
        "payer_email": email,
        "payer_id": payer_id,
    }


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


def trusted_cert_url(url: str) -> bool:
    parsed = urlparse(str(url))
    return parsed.scheme == "https" and (parsed.hostname or "").endswith(".paypal.com")


def segment(value: str) -> str:
    return quote(str(value), safe="")


def json_or_none(response: httpx.Response):
    try:
        return response.json()
    except ValueError:
        return None
