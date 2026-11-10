import threading
import time
from datetime import UTC, datetime

from parable.config import get_settings
from parable.paypal_core import PayPalError, cents_to_value, money

AUTHORIZATION_HONOR_S = 29 * 24 * 3600
ORPHAN_CAPACITY_CENTS = 10**12
CAPTURABLE = ("CREATED", "PARTIALLY_CAPTURED")
BLOCKED_AUTHORIZATION = {
    "CAPTURED": "AUTHORIZATION_ALREADY_CAPTURED",
    "VOIDED": "AUTHORIZATION_VOIDED",
}
DEMO_SELLER = {
    "payer_id": "MOCK-DEMO-SELLER",
    "name": "Demo Seller",
    "email": "demo.seller@example.com",
    "verified": True,
}


def not_found(kind: str, identifier: str) -> PayPalError:
    return PayPalError(404, "RESOURCE_NOT_FOUND", f"{kind} {identifier} does not exist")


def require_positive(cents: int) -> None:
    if cents <= 0:
        raise PayPalError(422, "INVALID_PARAMETER_VALUE", "amount must be greater than zero")


class MockPayPal:
    def __init__(self, public_base_url=None, clock=time.time):
        base = public_base_url if public_base_url is not None else get_settings().public_base_url
        self.public_base_url = base.rstrip("/")
        self._clock = clock
        self._lock = threading.RLock()
        self._counters: dict[str, int] = {}
        self._orders: dict[str, dict] = {}
        self._order_by_request: dict[str, str] = {}
        self._authorizations: dict[str, dict] = {}
        self._payouts: dict[str, dict] = {}

    def _next_id(self, kind: str) -> str:
        self._counters[kind] = self._counters.get(kind, 0) + 1
        return f"MOCK-{kind}-{self._counters[kind]:04d}"

    def _iso(self, offset_s: int = 0) -> str:
        moment = datetime.fromtimestamp(self._clock() + offset_s, tz=UTC)
        return moment.strftime("%Y-%m-%dT%H:%M:%SZ")

    def token(self) -> str:
        return "MOCK-ACCESS-TOKEN"

    def create_order(self, amount_cents, description, custom_id, return_url, cancel_url) -> dict:
        require_positive(amount_cents)
        with self._lock:
            known = self._order_by_request.get(custom_id)
            if known:
                return self._order_summary(self._orders[known])
            order_id = self._next_id("ORDER")
            self._orders[order_id] = {
                "id": order_id,
                "status": "CREATED",
                "amount_cents": amount_cents,
                "custom_id": custom_id,
                "description": description[:127],
                "return_url": return_url,
                "cancel_url": cancel_url,
                "payer_email": "",
                "payer_id": "",
            }
            self._order_by_request[custom_id] = order_id
            return self._order_summary(self._orders[order_id])

    def _order_summary(self, order: dict) -> dict:
        url = f"{self.public_base_url}/paypal/mock-approve?order={order['id']}"
        return {"id": order["id"], "status": order["status"], "approve_url": url}

    def _order(self, order_id: str) -> dict:
        order = self._orders.get(order_id)
        if order is None:
            raise not_found("order", order_id)
        return order

    def approve(self, order_id, payer_email="mock.buyer@example.com", payer_id="MOCK-BUYER") -> dict:
        with self._lock:
            order = self._order(order_id)
            if order["status"] == "CREATED":
                order.update(status="APPROVED", payer_email=payer_email, payer_id=payer_id)
            elif order["status"] != "APPROVED":
                raise PayPalError(422, "ORDER_NOT_APPROVABLE", f"order is {order['status']}")
            return self.get_order(order_id)

    def get_order(self, order_id) -> dict:
        with self._lock:
            order = self._order(order_id)
            unit = {
                "custom_id": order["custom_id"],
                "invoice_id": order["custom_id"],
                "description": order["description"],
                "amount": money(order["amount_cents"]),
            }
            return {"id": order["id"], "status": order["status"], "intent": "AUTHORIZE", "purchase_units": [unit]}

    def authorize_order(self, order_id) -> dict:
        with self._lock:
            order = self._order(order_id)
            if order["status"] == "COMPLETED":
                raise PayPalError(422, "ORDER_ALREADY_AUTHORIZED", "order was already authorized")
            if order["status"] != "APPROVED":
                raise PayPalError(422, "ORDER_NOT_APPROVED", "payer has not approved the order")
            authorization = self._new_authorization(order)
            order["status"] = "COMPLETED"
            return {
                "authorization_id": authorization["id"],
                "status": authorization["status"],
                "expiration_time": authorization["expiration_time"],
                "payer_email": order["payer_email"],
                "payer_id": order["payer_id"],
            }

    def _new_authorization(self, order: dict) -> dict:
        authorization = {
            "id": self._next_id("AUTH"),
            "status": "CREATED",
            "amount_cents": order["amount_cents"],
            "remaining_cents": order["amount_cents"],
            "invoice_id": order["custom_id"],
            "expiration_time": self._iso(AUTHORIZATION_HONOR_S),
        }
        self._authorizations[authorization["id"]] = authorization
        return authorization

    def _authorization(self, auth_id: str) -> dict:
        known = self._authorizations.get(auth_id)
        if known:
            return known
        if not auth_id.startswith("MOCK-AUTH-"):
            raise not_found("authorization", auth_id)
        orphan = {
            "id": auth_id,
            "status": "CREATED",
            "amount_cents": ORPHAN_CAPACITY_CENTS,
            "remaining_cents": ORPHAN_CAPACITY_CENTS,
            "invoice_id": "",
            "expiration_time": self._iso(AUTHORIZATION_HONOR_S),
        }
        self._authorizations[auth_id] = orphan
        return orphan

    def _require_open(self, authorization: dict) -> None:
        blocked = BLOCKED_AUTHORIZATION.get(authorization["status"])
        if blocked:
            raise PayPalError(422, blocked, f"authorization is {authorization['status']}")

    def capture_authorization(self, auth_id, amount_cents, invoice_id, final=True) -> dict:
        require_positive(amount_cents)
        with self._lock:
            authorization = self._authorization(auth_id)
            self._require_open(authorization)
            if amount_cents > authorization["remaining_cents"]:
                raise PayPalError(422, "CAPTURE_AMOUNT_EXCEEDS_AUTHORIZATION", "amount is above what is held")
            authorization["remaining_cents"] -= amount_cents
            authorization["status"] = "CAPTURED" if final else "PARTIALLY_CAPTURED"
            return {"capture_id": self._next_id("CAPTURE"), "status": "COMPLETED"}

    def void_authorization(self, auth_id) -> dict:
        with self._lock:
            authorization = self._authorization(auth_id)
            if authorization["status"] == "VOIDED":
                raise PayPalError(422, "AUTHORIZATION_ALREADY_VOIDED", "authorization was already voided")
            self._require_open(authorization)
            authorization["status"] = "VOIDED"
            return {"status": "VOIDED"}

    def get_authorization(self, auth_id) -> dict:
        with self._lock:
            authorization = self._authorization(auth_id)
            return {
                "id": authorization["id"],
                "status": authorization["status"],
                "amount": money(authorization["amount_cents"]),
                "invoice_id": authorization["invoice_id"],
                "expiration_time": authorization["expiration_time"],
            }

    def create_payout(self, batch_id, receiver_email, amount_cents, note) -> dict:
        require_positive(amount_cents)
        with self._lock:
            payout = self._payouts.get(batch_id)
            if payout is None:
                payout = self._new_payout(batch_id, receiver_email, amount_cents, note)
            return {"payout_batch_id": payout["payout_batch_id"], "batch_status": payout["batch_status"]}

    def _new_payout(self, batch_id, receiver_email, amount_cents, note) -> dict:
        item = {
            "payout_item_id": self._next_id("PAYOUT-ITEM"),
            "transaction_status": "SUCCESS",
            "payout_item": {
                "receiver": receiver_email,
                "note": note,
                "sender_item_id": batch_id,
                "amount": {"value": cents_to_value(amount_cents), "currency": "USD"},
            },
        }
        payout = {"payout_batch_id": self._next_id("PAYOUT"), "batch_status": "SUCCESS", "items": [item]}
        self._payouts[batch_id] = payout
        return payout

    def get_payout(self, batch_id) -> dict:
        with self._lock:
            for key, payout in self._payouts.items():
                if batch_id in (key, payout["payout_batch_id"]):
                    return {"batch_status": payout["batch_status"], "items": list(payout["items"])}
            raise not_found("payout batch", batch_id)

    def verify_webhook(self, headers, body, webhook_id) -> bool:
        return True

    def oauth_authorize_url(self, state, redirect_uri) -> str:
        return f"{self.public_base_url}/paypal/mock-login?state={state}"

    def exchange_code(self, code) -> str:
        return f"MOCK-USER-TOKEN-{code}"

    def userinfo(self, user_token) -> dict:
        return dict(DEMO_SELLER)
