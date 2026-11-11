from fastapi import Request, Response
from pydantic import BaseModel, Field

from parable import identity
from parable.benchmarks import model_auth
from parable.config import get_settings
from parable.errors import LabError
from parable.lab import llm, quota
from parable.lab.consts import INTERVALS, MAX_BARS
from parable.lab.llm import AiAuth


class DataRequest(BaseModel):
    symbol: str | None = Field(default=None, max_length=64)
    interval: str | None = Field(default=None, max_length=4)
    dataset_id: str | None = Field(default=None, max_length=24)
    start: float | None = None
    end: float | None = None
    limit: int | None = Field(default=None, ge=1, le=MAX_BARS)


def account_of(request: Request) -> str | None:
    seller = identity.current_seller(request)
    return seller["id"] if seller else None


def signin(request: Request) -> str:
    account = account_of(request)
    if account is None:
        raise LabError(401, "unauthorized", "sign in with PayPal first")
    return account


def visitor(request: Request, response: Response | None = None) -> str:
    return quota.visitor_id(request, response)


def rate(who: str, bucket: str, limit: int, window_s: int = 60) -> None:
    quota.limiter.hit(f"{bucket}:{who}", limit, window_s)


def rate_lab(who: str) -> None:
    rate(who, "lab", get_settings().rate_lab_per_minute)


def rate_ai(who: str) -> None:
    rate(who, "ai", get_settings().rate_ai_per_minute)


def own_auth(request: Request) -> AiAuth | None:
    h = request.headers
    return llm.auth_from_headers(h.get("x-ai-provider"), h.get("x-ai-model"), h.get("x-ai-key"))


def check_symbol_interval(symbol: str, interval: str) -> None:
    if interval not in INTERVALS:
        raise LabError(400, "bad_request", f"interval must be one of {', '.join(INTERVALS)}")
    head, sep, code = str(symbol).partition(":")
    if not sep or not code or not head:
        raise LabError(400, "bad_request", "symbols look like provider:CODE")


def pick_ai(who: str, model: str | None, own: AiAuth | None) -> tuple[AiAuth, bool]:
    if model:
        return model_auth(model, own)
    if own is not None:
        return own, False
    for info in llm.platform_models():
        if info.available:
            return AiAuth(provider="platform", model=info.id), True
    raise LabError(503, "model_unavailable", "no AI model is available, add your own key")


def charge(who: str, platform: bool) -> dict:
    if platform:
        quota.take_free_try(who)
    return quota.free_tries(who)
