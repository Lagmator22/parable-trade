import hmac

from fastapi import APIRouter, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from parable import deals, identity
from parable.config import get_settings
from parable.errors import LabError
from parable.paypal import is_mock
from parable.routes_support import account_of, charge, own_auth, pick_ai, rate, rate_ai, signin, visitor

router = APIRouter()


class ChecklistBody(BaseModel):
    brief: str


class CreateDealBody(BaseModel):
    title: str
    brief: str
    checklist: list[dict]
    amount_cents: int
    freelancer_email: str
    built_by: str | None = None


class FundBody(BaseModel):
    order_id: str


class SubmitBody(BaseModel):
    work_text: str
    work_url: str | None = None


def _with_timeline(view: dict, deal_id: str, role: str) -> dict:
    return {**view, "timeline": deals.timeline(deal_id), "role": role}


@router.get("/api/deals/demo-signin")
def demo_signin_route():
    seller = identity.upsert_seller("SBX-GURMAN", "Gurman Singh", "sb-b47v8l53876686@business.example.com", True)
    res = RedirectResponse("/#deals", status_code=302)
    identity.sign_in(res, seller)
    return res


@router.post("/api/deals/checklist")
def build_checklist_route(body: ChecklistBody, request: Request):
    who = signin(request)
    deals.validate_brief(body.brief)
    rate_ai(who)
    try:
        auth, platform = pick_ai(who, None, own_auth(request))
    except LabError as err:
        if err.code != "model_unavailable":
            raise
        auth = deals.platform_auth()
        platform = auth is not None
    tries = charge(who, platform)
    built = deals.build_checklist(body.brief, auth)
    return {**built, "free_tries": tries}


@router.post("/api/deals")
def create_deal_route(body: CreateDealBody, request: Request):
    who = signin(request)
    rate(who, "deals", 10, 3600)
    deal = deals.create_deal(
        who, body.title, body.brief, body.checklist, body.amount_cents, body.freelancer_email, body.built_by
    )
    return _with_timeline(deals.client_view(deal), deal["id"], "client")


@router.get("/api/deals")
def list_deals_route(request: Request):
    who = signin(request)
    return deals.list_for_client(who)


@router.get("/api/deals/{deal_id}")
def get_deal_route(deal_id: str, request: Request, k: str = ""):
    deal = deals.load_deal(deal_id)
    who = account_of(request)
    if who and who == deal["client_id"]:
        return _with_timeline(deals.client_view(deal), deal_id, "client")
    if k and hmac.compare_digest(k, deal["share_token"]):
        return _with_timeline(deals.party_view(deal), deal_id, "freelancer")
    return _with_timeline(deals.public_view(deal), deal_id, "visitor")


@router.post("/api/deals/{deal_id}/order")
def order_deal_route(deal_id: str, request: Request):
    who = signin(request)
    deal = deals.owned_deal(deal_id, who)
    order = deals.start_order(deal, get_settings().public_base_url)
    return {**order, "mock": is_mock()}


@router.post("/api/deals/{deal_id}/fund")
def fund_deal_route(deal_id: str, body: FundBody, request: Request):
    who = signin(request)
    deal = deals.owned_deal(deal_id, who)
    seller = identity.current_seller(request) or {}
    payer = {"email": seller.get("email") or "", "payer_id": seller.get("paypal_payer_id") or ""}
    funded = deals.fund(deal, body.order_id, payer)
    return _with_timeline(deals.client_view(funded), deal_id, "client")


@router.post("/api/deals/{deal_id}/submit")
def submit_deal_route(deal_id: str, body: SubmitBody, request: Request, response: Response, k: str = ""):
    deal = deals.load_deal(deal_id)
    if not k or not hmac.compare_digest(k, deal["share_token"]):
        raise LabError(403, "forbidden", "invalid freelancer link")
    rate(visitor(request, response), "deal-submit", 6, 3600)
    updated = deals.submit(deal, body.work_text, body.work_url)
    return _with_timeline(deals.party_view(updated), deal_id, "freelancer")


@router.post("/api/deals/{deal_id}/release")
def release_deal_route(deal_id: str, request: Request):
    who = signin(request)
    deal = deals.owned_deal(deal_id, who)
    released = deals.release(deal, by="client")
    return _with_timeline(deals.client_view(released), deal_id, "client")


@router.post("/api/deals/{deal_id}/refund")
def refund_deal_route(deal_id: str, request: Request):
    who = signin(request)
    deal = deals.owned_deal(deal_id, who)
    refunded = deals.refund(deal)
    return _with_timeline(deals.client_view(refunded), deal_id, "client")
