from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field

from parable import agents
from parable.errors import LabError
from parable.lab import compiler, jobs, llm, quota
from parable.lab.backtest import run_backtest
from parable.lab.describe import CompileResult, describe_spec
from parable.lab.optimize import optimize
from parable.lab.questionnaire import DEFAULTS, check_answers, questions
from parable.lab.spec import SpecError, parse_spec, spec_hash
from parable.lab.templates import template_spec
from parable.models import StrategySpec
from parable.routes_support import (DataRequest, account_of, charge, check_symbol_interval, own_auth, pick_ai, rate,
                                    rate_ai, rate_lab, signin, visitor)

router = APIRouter()

OPTIMIZE_PER_MINUTE = 5
DEFAULT_LIMIT = 2000


class CompileBody(BaseModel):
    steps: str | None = Field(default=None, max_length=8000)
    symbol: str = Field(max_length=64)
    interval: str = Field(max_length=4)
    model: str | None = Field(default=None, max_length=90)
    answers: dict[str, str] | None = None
    base: dict | None = None


class IdeasBody(BaseModel):
    spec: dict
    steps: str = Field(max_length=8000)
    model: str | None = Field(default=None, max_length=90)


class SpecBody(BaseModel):
    spec: dict


class BacktestBody(DataRequest):
    spec: dict


class OptimizeBody(BacktestBody):
    top_k: int = Field(default=5, ge=1, le=20)


def compile_view(built: CompileResult, tries: dict) -> dict:
    return {"spec": built.spec.model_dump(), "summary": built.summary, "rules": [r.model_dump() for r in built.rules],
            "built_by": built.built_by, "attempts": built.attempts, "free_tries": tries}


def parsed(raw: dict) -> StrategySpec:
    return parse_spec(raw)


def spec_error(err: SpecError) -> LabError:
    return LabError(422, "invalid_spec", "the strategy has problems", {"errors": err.errors})


def questionnaire_build(answers: dict, symbol: str, interval: str) -> CompileResult:
    chosen = check_answers(answers)
    plain = all(chosen[k] == v for k, v in DEFAULTS.items())
    return compiler.build_from_answers(answers, symbol, interval,
                                       built_by=f"template:{chosen['family']}" if plain else "questionnaire")


@router.get("/api/ai/models")
def models(request: Request, response: Response):
    who = visitor(request, response)
    own = own_auth(request)
    out = {"platform": [m.model_dump() for m in llm.platform_models()], "own": [],
           "free_tries": quota.free_tries(who), "key_ok": None}
    if own is not None:
        try:
            names = llm.listed(own)[:40] or llm.DEFAULTS.get(own.provider, [])
            out["key_ok"] = True
        except (LabError, KeyError, TypeError, AttributeError):
            names = llm.DEFAULTS.get(own.provider, [])
            out["key_ok"] = False
        out["own"] = [llm.ModelInfo(id=f"{own.provider}:{m}", provider=own.provider, model=m, label=m, available=True,
                                    free=False).model_dump() for m in names]
    return out


@router.get("/api/ai/questionnaire")
def questionnaire():
    return {"questions": [q.model_dump() for q in questions()]}


@router.post("/api/ai/compile")
def compile_route(body: CompileBody, request: Request, response: Response):
    who = visitor(request, response)
    check_symbol_interval(body.symbol, body.interval)
    rate_ai(who)
    if body.model is None and body.answers is not None:
        return compile_view(questionnaire_build(body.answers, body.symbol, body.interval), quota.free_tries(who))
    if not (body.steps or "").strip():
        raise LabError(400, "bad_request", "describe the strategy steps first")
    try:
        base = parsed(body.base) if body.base else None
    except SpecError as err:
        raise spec_error(err) from None
    auth, platform = pick_ai(who, body.model, own_auth(request))
    tries = charge(who, platform)
    quota.hit_llm_budget()
    built = compiler.compile_steps(body.steps, body.symbol, body.interval, auth, base=base)
    return compile_view(built, tries)


@router.post("/api/ai/ideas")
def ideas_route(body: IdeasBody, request: Request, response: Response):
    who = visitor(request, response)
    rate_ai(who)
    try:
        base = parsed(body.spec)
    except SpecError as err:
        raise spec_error(err) from None
    auth, platform = pick_ai(who, body.model, own_auth(request))
    charge(who, platform)
    found = compiler.ideas(base, body.steps, auth)
    tries = quota.free_tries(who)
    return {"ideas": [compile_view(i, tries) for i in found], "free_tries": tries}


@router.get("/api/lab/templates/{template_id}")
def template_route(template_id: str, request: Request, response: Response, symbol: str, interval: str):
    who = visitor(request, response)
    check_symbol_interval(symbol, interval)
    spec = template_spec(template_id, symbol, interval)
    built = CompileResult(spec=spec, summary=spec.summary, rules=describe_spec(spec), built_by=spec.built_by, attempts=1)
    return compile_view(built, quota.free_tries(who))


@router.post("/api/lab/validate")
def validate_route(body: SpecBody):
    try:
        spec = parsed(body.spec)
    except SpecError as err:
        return {"ok": False, "errors": err.errors, "spec_hash": None, "rules": []}
    return {"ok": True, "errors": [], "spec_hash": spec_hash(spec), "rules": [r.model_dump() for r in describe_spec(spec)]}


def lab_data(request: Request, body: DataRequest, spec: StrategySpec) -> dict:
    return agents.resolve_data(account_of(request), body.symbol or spec.symbol, body.interval or spec.interval,
                               limit=body.limit or DEFAULT_LIMIT, start=body.start, end=body.end,
                               dataset_id=body.dataset_id)


def tested(spec: StrategySpec, data: dict) -> dict:
    return run_backtest(spec, data["bars"], symbol=data["symbol"], interval=data["interval"], quote=data["quote"],
                        source_kind=data["source_kind"])


@router.post("/api/lab/backtest")
def backtest_route(body: BacktestBody, request: Request, response: Response):
    rate_lab(visitor(request, response))
    try:
        spec = parsed(body.spec)
    except SpecError as err:
        raise spec_error(err) from None
    return tested(spec, lab_data(request, body, spec))


@router.post("/api/lab/optimize")
def optimize_route(body: OptimizeBody, request: Request):
    who = signin(request)
    rate(who, "optimize", OPTIMIZE_PER_MINUTE)
    try:
        spec = parsed(body.spec)
    except SpecError as err:
        raise spec_error(err) from None
    data = lab_data(request, body, spec)

    def work(progress) -> dict:
        try:
            return optimize(spec, data["bars"], top_k=body.top_k, progress=progress,
                            partial=lambda part: progress(None, None, part))
        except ValueError as err:
            raise LabError(400, "bad_request", str(err)) from None

    return {"job_id": jobs.start("optimize", who, work)}
