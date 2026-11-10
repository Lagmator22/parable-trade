from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, Field

from parable import analyst, bot_runner, diligence, ledger, market, prices, shopper
from parable.api_support import public_run, require_seller
from parable.config import get_settings, paypal_mode
from parable.models import PRESETS
from parable.paypal import is_mock

router = APIRouter()

PRICE_POINTS = 120


class PurchaseRequest(BaseModel):
    listing_id: str
    via: str = "web"


class ApproveRequest(BaseModel):
    order_id: str


class ShopperRequest(BaseModel):
    query: str = Field(max_length=400)
    budget_cents: int | None = Field(default=None, ge=0)


def dollars(price: int) -> float:
    return price / prices.PRICE_DECIMALS


@router.get("/api/info")
def info():
    settings = get_settings()
    mock = is_mock()
    return {
        "paypal_mode": "mock" if mock else paypal_mode(),
        "paypal_client_id": "" if mock else settings.paypal_client_id,
        "currency": "USD",
        "platform_fee_bps": settings.platform_fee_bps,
        "price_source": settings.price_source,
        "eth_price_usd": dollars(prices.price()),
        "strategies": [{"id": key, "text": text} for key, text in PRESETS.items()],
        "brains": [{"brain": name, "available": ready} for name, ready in bot_runner.available_brains().items()],
        "analyst": analyst.brain_name() if analyst.available() else "rules",
        "ledger_head": ledger.head(),
    }


@router.get("/api/stats")
def stats():
    return market.market_stats()


def current_point() -> list:
    stamp, value = prices.record_sample()
    return [stamp, dollars(value)]


@router.get("/api/prices")
def price_points():
    points = [[stamp, dollars(value)] for stamp, value in prices.history(PRICE_POINTS)]
    return {"points": points or [current_point()]}


@router.get("/api/listings")
def listings():
    return market.list_listings()


@router.get("/api/listings/{listing_id}")
def listing(listing_id: str):
    return {**market.get_listing(listing_id), "runs": [public_run(run) for run in market.listing_runs(listing_id)]}


@router.post("/api/listings")
def create_listing(data: market.ListingInput, seller: dict = Depends(require_seller)):
    return market.create_listing(seller["id"], data)


@router.post("/api/listings/{listing_id}/pause")
def pause_listing(listing_id: str, seller: dict = Depends(require_seller)):
    return market.pause_listing(seller["id"], listing_id)


@router.post("/api/listings/{listing_id}/practice")
def practice(listing_id: str, seller: dict = Depends(require_seller)):
    return public_run(market.start_practice(seller["id"], listing_id))


@router.get("/api/listings/{listing_id}/diligence")
def listing_diligence(listing_id: str):
    return diligence.report(listing_id)


@router.post("/api/shopper")
def shop(request: ShopperRequest):
    answer = shopper.recommend(request.query, request.budget_cents)
    found = {item["id"]: item for item in market.list_listings()}
    return {**answer, "listing": found.get(answer["listing_id"]),
            "alternative_listings": [found[key] for key in answer["alternatives"] if key in found]}


@router.post("/api/purchases")
def new_purchase(request: PurchaseRequest):
    return market.start_purchase(request.listing_id, request.via)


@router.post("/api/purchases/{purchase_id}/approve")
def approve(purchase_id: str, request: ApproveRequest, x_buyer_token: str | None = Header(default=None)):
    market.confirm_approval(purchase_id, request.order_id)
    return market.get_purchase(purchase_id, x_buyer_token)


@router.get("/api/purchases/{purchase_id}")
def purchase(purchase_id: str, x_buyer_token: str | None = Header(default=None)):
    return market.get_purchase(purchase_id, x_buyer_token)


@router.post("/api/purchases/{purchase_id}/retry")
def retry(purchase_id: str, x_buyer_token: str | None = Header(default=None)):
    market.retry_settlement(purchase_id)
    return market.get_purchase(purchase_id, x_buyer_token)
