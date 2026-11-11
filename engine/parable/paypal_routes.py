import logging
from urllib.parse import parse_qs

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from parable import market
from parable.db import one
from parable.errors import LabError, MarketError
from parable.identity import current_seller
from parable.paypal import PayPalError, get_paypal, is_mock
from parable.paypal_pages import approve_page, message_page

log = logging.getLogger("parable.paypal_routes")

router = APIRouter()

MAX_FORM_BYTES = 4096


def go(location: str, status: int = 302) -> RedirectResponse:
    return RedirectResponse(location, status_code=status)


def purchase_page(purchase_id: str) -> str:
    return f"/#purchase/{purchase_id}"


def not_mock() -> HTMLResponse:
    return HTMLResponse(message_page("Not available", "Simulated PayPal pages are disabled."), status_code=404)


def unknown_order() -> HTMLResponse:
    return HTMLResponse(message_page("Order not found", "This simulated order does not exist (the server may "
                                     "have restarted)."), status_code=404)


def order_details(order_id: str) -> dict | None:
    try:
        return get_paypal().get_order(order_id)
    except PayPalError:
        return None


@router.get("/paypal/mock-approve")
def mock_approve_page(order: str = ""):
    if not is_mock():
        return not_mock()
    details = order_details(order)
    if details is None:
        return unknown_order()
    unit = details["purchase_units"][0]
    return HTMLResponse(approve_page(order, unit["amount"]["value"], unit.get("description", "")))


async def read_form(request: Request) -> dict[str, str]:
    body = (await request.body())[:MAX_FORM_BYTES].decode("utf-8", errors="replace")
    return {key: values[0] for key, values in parse_qs(body).items()}


@router.post("/paypal/mock-approve")
async def mock_approve_submit(request: Request):
    if not is_mock():
        return not_mock()
    form = await read_form(request)
    order_id = form.get("order", "")
    details = order_details(order_id)
    if details is None:
        return unknown_order()
    purchase_id = details["purchase_units"][0]["custom_id"]
    if form.get("decision") == "cancel":
        return go(f"/paypal/cancel?purchase={purchase_id}", 303)
    payer = current_seller(request)
    if payer:
        get_paypal().approve(order_id, payer["email"], payer["paypal_payer_id"])
    else:
        get_paypal().approve(order_id)
    return go(f"/paypal/return?token={order_id}&purchase={purchase_id}", 303)


def purchase_id_for(request: Request, token: str, purchase: str) -> str:
    viewer = current_seller(request)
    found = one("SELECT id, buyer_id FROM purchases WHERE id = ?", (purchase,)) if purchase else \
        market.find_purchase_by_order(token)
    if viewer is None or found is None or found.get("buyer_id") != viewer["id"]:
        return ""
    return found["id"]


@router.get("/paypal/return")
def paypal_return(request: Request, token: str = "", purchase: str = ""):
    purchase_id = purchase_id_for(request, token, purchase)
    if not purchase_id:
        return go("/#purchases")
    try:
        market.confirm_approval(purchase_id, token)
    except (PayPalError, MarketError, LabError) as problem:
        log.warning("approval for %s failed: %s", purchase_id, problem)
    return go(purchase_page(purchase_id))


@router.get("/paypal/cancel")
def paypal_cancel(request: Request, purchase: str = "", token: str = ""):
    purchase_id = purchase_id_for(request, token, purchase)
    if not purchase_id:
        return go("/#purchases")
    try:
        market.cancel_purchase(purchase_id)
    except (MarketError, LabError) as problem:
        log.warning("cancel for %s failed: %s", purchase_id, problem)
    return go(purchase_page(purchase_id))
