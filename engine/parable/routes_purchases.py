from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field

from parable import market, me_views, runs
from parable.api_support import require_seller
from parable.config import get_settings
from parable.lab import quota
from parable.listings import listing_row
from parable.live_symbols import require_live_symbol
from parable.purchase_views import buyer_purchase, entitled_purchase, get_purchase, license_download
from parable.run_views import public_run

router = APIRouter()

MICRO = 1_000_000


class PurchaseRequest(BaseModel):
    listing_id: str


class ApproveRequest(BaseModel):
    order_id: str


class RunRequest(BaseModel):
    start_cash: float | None = Field(default=None, gt=0, le=1e9)
    max_loss_bps: int = Field(default=2000, ge=10, le=5000)
    lease_seconds: int = Field(default=86_400, ge=60, le=2_592_000)


@router.post("/api/purchases")
def new_purchase(request: PurchaseRequest, buyer: dict = Depends(require_seller)):
    quota.limiter.hit(f"purchases:{buyer['id']}", get_settings().rate_purchases_per_hour, 3600)
    return market.start_purchase(request.listing_id, buyer["id"])


@router.post("/api/purchases/{purchase_id}/approve")
def approve(purchase_id: str, request: ApproveRequest, buyer: dict = Depends(require_seller)):
    buyer_purchase(purchase_id, buyer["id"])
    market.confirm_approval(purchase_id, request.order_id)
    return get_purchase(purchase_id, buyer["id"])


@router.get("/api/purchases/{purchase_id}")
def purchase(purchase_id: str, buyer: dict = Depends(require_seller)):
    return get_purchase(purchase_id, buyer["id"])


@router.post("/api/purchases/{purchase_id}/retry")
def retry(purchase_id: str, buyer: dict = Depends(require_seller)):
    buyer_purchase(purchase_id, buyer["id"])
    market.retry_settlement(purchase_id)
    return get_purchase(purchase_id, buyer["id"])


@router.get("/api/purchases/{purchase_id}/license")
def download_license(purchase_id: str, buyer: dict = Depends(require_seller)):
    name, body = license_download(purchase_id, buyer["id"])
    return Response(body, media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.post("/api/purchases/{purchase_id}/run")
def run_purchase(purchase_id: str, options: RunRequest | None = None, buyer: dict = Depends(require_seller)):
    purchase_row = entitled_purchase(purchase_id, buyer["id"])
    listing = listing_row(purchase_row["listing_id"])
    require_live_symbol(listing["symbol"], "a live run")
    chosen = options or RunRequest()
    cash = int(round(chosen.start_cash * MICRO)) if chosen.start_cash else None
    run = runs.get_manager().start_for_version(
        buyer["id"], listing["version_id"], listing["symbol"], listing["interval"], "practice",
        f"{listing['title']} (my copy)", start_cash=cash, max_loss_bps=chosen.max_loss_bps,
        lease_seconds=chosen.lease_seconds, listing_id=listing["id"])
    return public_run(run, buyer["id"])


@router.get("/api/me/agents")
def my_agents(seller: dict = Depends(require_seller)):
    return me_views.my_agents(seller["id"])


@router.get("/api/me/purchases")
def my_purchases(seller: dict = Depends(require_seller)):
    return me_views.my_purchases(seller["id"])


@router.get("/api/me/sales")
def my_sales(seller: dict = Depends(require_seller)):
    return me_views.my_sales(seller["id"])
