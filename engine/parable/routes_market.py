from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field

from parable import analyst, diligence, ledger, market, proofs, shopper
from parable.api_support import require_seller
from parable.config import get_settings, paypal_mode
from parable.errors import LabError
from parable.identity import current_seller
from parable.lab import quota
from parable.lab.consts import (ASSET_KINDS, INTERVALS, MAX_BARS, MAX_FORMULA_LEN, MAX_GRID, MAX_PARAMS,
                                MAX_SPEC_BYTES, MAX_STEPS_CHARS, MIN_BARS)
from parable.lab.templates import list_templates
from parable.models import NewListing
from parable.paypal import is_mock
from parable.routes_support import rate, visitor

router = APIRouter()

SHOPPER_PER_MINUTE = 6
DILIGENCE_PER_MINUTE = 20


class ShopperRequest(BaseModel):
    query: str = Field(max_length=400)
    budget_cents: int | None = Field(default=None, ge=0)


class BenchmarkAttach(BaseModel):
    benchmark_id: str


class RerunRequest(BaseModel):
    refetch: bool = False


class TestDriveRequest(BaseModel):
    symbol: str | None = None
    interval: str | None = None
    start: float | None = None
    end: float | None = None


def limits() -> dict:
    settings = get_settings()
    return {
        "max_formula_len": MAX_FORMULA_LEN, "max_params": MAX_PARAMS, "max_grid": MAX_GRID,
        "max_spec_bytes": MAX_SPEC_BYTES, "max_steps_chars": MAX_STEPS_CHARS, "min_bars": MIN_BARS,
        "max_bars": MAX_BARS, "upload_max_bytes": settings.upload_max_bytes,
        "upload_max_rows": settings.upload_max_rows, "benchmark_max_models": settings.benchmark_max_models,
        "max_agents": settings.max_agents_per_account, "max_versions": settings.max_versions_per_agent,
        "max_datasets": settings.max_datasets_per_account,
    }


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
        "analyst": analyst.brain_name() if analyst.available() else "rules",
        "kinds": list(ASSET_KINDS),
        "intervals": list(INTERVALS),
        "templates": list_templates(),
        "limits": limits(),
        "ai": {"free_tries_per_day": settings.ai_free_tries_per_day},
        "ledger_head": ledger.head(),
    }


@router.get("/api/stats")
def stats():
    return market.market_stats()


@router.get("/api/listings")
def listings(kind: str | None = None, mode: str | None = None, sort: str = "new"):
    return market.list_listings(kind, mode, sort)


def visible_listing(listing_id: str, request: Request) -> None:
    summary = market.listing_summary(listing_id)
    if summary["active"]:
        return
    viewer = current_seller(request)
    if viewer is None or viewer["id"] != summary["seller"]["id"]:
        raise LabError(404, "not_found", "listing not found")


@router.get("/api/listings/{listing_id}")
def listing(listing_id: str, request: Request):
    visible_listing(listing_id, request)
    return market.listing_detail(listing_id)


@router.post("/api/listings")
def create_listing(data: NewListing, seller: dict = Depends(require_seller)):
    created = market.create_listing(seller["id"], data)
    return market.listing_detail(created["id"])


@router.post("/api/listings/{listing_id}/pause")
def pause_listing(listing_id: str, seller: dict = Depends(require_seller)):
    market.pause_listing(seller["id"], listing_id)
    return market.listing_detail(listing_id)


@router.post("/api/listings/{listing_id}/resume")
def resume_listing(listing_id: str, seller: dict = Depends(require_seller)):
    market.resume_listing(seller["id"], listing_id)
    return market.listing_detail(listing_id)


@router.post("/api/listings/{listing_id}/benchmark")
def attach_benchmark(listing_id: str, body: BenchmarkAttach, seller: dict = Depends(require_seller)):
    market.attach_benchmark(seller["id"], listing_id, body.benchmark_id)
    return market.listing_detail(listing_id)


@router.post("/api/listings/{listing_id}/rerun")
def rerun(listing_id: str, request: Request, response: Response, body: RerunRequest | None = None):
    visitor = quota.visitor_id(request, response)
    return proofs.rerun_listing(listing_id, visitor, bool(body and body.refetch))


@router.post("/api/listings/{listing_id}/test-drive")
def test_drive(listing_id: str, request: Request, response: Response, body: TestDriveRequest | None = None):
    visitor = quota.visitor_id(request, response)
    options = body.model_dump() if body else {}
    return proofs.test_drive(listing_id, visitor, **options)


@router.get("/api/listings/{listing_id}/diligence")
def listing_diligence(listing_id: str, request: Request, response: Response):
    visible_listing(listing_id, request)
    rate(visitor(request, response), "diligence", DILIGENCE_PER_MINUTE)
    return diligence.report(listing_id)


@router.post("/api/shopper")
def shop(body: ShopperRequest, request: Request, response: Response):
    rate(visitor(request, response), "shopper", SHOPPER_PER_MINUTE)
    quota.hit_llm_budget()
    answer = shopper.recommend(body.query, body.budget_cents)
    found = {item["id"]: item for item in market.list_listings()}
    return {**answer, "listing": found.get(answer["listing_id"]),
            "alternative_listings": [found[key] for key in answer["alternatives"] if key in found]}

