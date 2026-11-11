from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field

from parable import agents, benchmarks, proofs, runs
from parable.api_support import public_run
from parable.errors import LabError
from parable.lab import jobs, markets, quota
from parable.lab.backtest import run_backtest
from parable.lab.spec import SpecError, load_spec, parse_spec
from parable.routes_support import DataRequest, check_symbol_interval, own_auth, rate_lab, signin, visitor

router = APIRouter()

DEFAULT_LIMIT = 2000
MICRO = 1_000_000


class NewAgent(BaseModel):
    name: str = Field(max_length=80)
    symbol: str = Field(max_length=64)
    interval: str = Field(max_length=4)


class NewVersion(BaseModel):
    spec: dict
    steps_text: str = Field(default="", max_length=8000)
    built_by: str | None = Field(default=None, max_length=80)


class PracticeBody(BaseModel):
    start_cash: float | None = Field(default=None, gt=0, le=1e12)
    max_loss_bps: int = Field(default=2000, ge=10, le=10_000)
    lease_seconds: int = Field(default=86_400, ge=60, le=2_592_000)


class BenchmarkBody(DataRequest):
    steps: str | None = Field(default=None, max_length=8000)
    models: list[str] = Field(min_length=1, max_length=12)


class AdoptBody(BaseModel):
    model: str = Field(max_length=90)


@router.get("/api/agents")
def list_agents(request: Request):
    return agents.list_agents(signin(request))


@router.post("/api/agents")
def create_agent(body: NewAgent, request: Request):
    owner = signin(request)
    check_symbol_interval(body.symbol, body.interval)
    created = agents.create_agent(owner, body.name, body.symbol, body.interval)
    return agents.agent_detail(owner, created["id"])


@router.get("/api/agents/{agent_id}")
def get_agent(agent_id: str, request: Request):
    return agents.agent_detail(signin(request), agent_id)


@router.delete("/api/agents/{agent_id}")
def delete_agent(agent_id: str, request: Request):
    agents.delete_agent(signin(request), agent_id)
    return {"ok": True}


@router.post("/api/agents/{agent_id}/versions")
def add_version(agent_id: str, body: NewVersion, request: Request):
    owner = signin(request)
    try:
        spec = parse_spec(body.spec)
    except SpecError as err:
        raise LabError(422, "invalid_spec", "the strategy has problems", {"errors": err.errors}) from None
    return agents.save_version(owner, agent_id, spec, body.steps_text, body.built_by)


@router.get("/api/agents/{agent_id}/versions/{version_id}")
def get_version(agent_id: str, version_id: str, request: Request):
    return agents.agent_version(signin(request), agent_id, version_id)


@router.post("/api/agents/{agent_id}/versions/{version_id}/backtest")
def backtest_version(agent_id: str, version_id: str, body: DataRequest, request: Request, response: Response):
    owner = signin(request)
    rate_lab(owner)
    found = agents.agent_version(owner, agent_id, version_id)
    spec = load_spec(found["id"])
    data = agents.resolve_data(owner, body.symbol or spec.symbol, body.interval or spec.interval,
                               limit=body.limit or DEFAULT_LIMIT, start=body.start, end=body.end,
                               dataset_id=body.dataset_id)
    result = run_backtest(spec.model_copy(update={"symbol": data["symbol"], "interval": data["interval"]})
                          if (data["symbol"], data["interval"]) != (spec.symbol, spec.interval) else spec,
                          data["bars"], symbol=data["symbol"], interval=data["interval"], quote=data["quote"],
                          source_kind=data["source_kind"])
    row = proofs.store_proof("backtest", version_id, spec, result, bars=data["bars"])
    return proofs.proof_view(row, owner=True)


@router.post("/api/agents/{agent_id}/versions/{version_id}/run")
def practice_run(agent_id: str, version_id: str, body: PracticeBody, request: Request):
    owner = signin(request)
    found = agents.agent_version(owner, agent_id, version_id)
    spec = load_spec(found["id"])
    if spec.symbol.startswith("upload:"):
        raise LabError(400, "bad_request", "uploaded data cannot run live, pick a market symbol")
    markets.latest(spec.symbol)
    cash = int(body.start_cash * MICRO) if body.start_cash else None
    run = runs.get_manager().start_for_version(owner, version_id, spec.symbol, spec.interval, "practice", spec.name,
                                               start_cash=cash, max_loss_bps=body.max_loss_bps,
                                               lease_seconds=body.lease_seconds)
    return public_run(run)


@router.post("/api/agents/{agent_id}/benchmark")
def start_benchmark(agent_id: str, body: BenchmarkBody, request: Request, response: Response):
    owner = signin(request)
    agent = agents.owned_agent(owner, agent_id)
    own = own_auth(request)
    steps = (body.steps or "").strip()
    if not steps and agent["latest_version_id"]:
        steps = agents.owner_version(owner, agent["latest_version_id"])["steps_text"].strip()
    if not steps:
        raise LabError(400, "bad_request", "describe the strategy steps first")
    data = agents.resolve_data(owner, body.symbol or agent["symbol"], body.interval or agent["interval"],
                               limit=body.limit or DEFAULT_LIMIT, start=body.start, end=body.end,
                               dataset_id=body.dataset_id)
    models = list(dict.fromkeys(body.models))
    platform = 0
    for model in models:
        try:
            platform += int(benchmarks.model_auth(model, own)[1])
        except LabError:
            continue
    if platform and quota.free_tries(owner)["remaining"] < platform:
        raise LabError(429, "free_tries_used", "not enough free AI tries left for those models, add your own key",
                       {"free_tries": quota.free_tries(owner)})
    for _ in range(platform):
        quota.take_free_try(owner)

    def work(progress) -> dict:
        return benchmarks.run_benchmark(owner, agent_id, steps, models, data["symbol"], data["interval"],
                                        data["bars"], data["source_kind"], own, progress, quote=data["quote"])

    return {"job_id": jobs.start("benchmark", owner, work), "free_tries": quota.free_tries(owner)}


@router.get("/api/benchmarks/{benchmark_id}")
def get_benchmark(benchmark_id: str, request: Request):
    return benchmarks.benchmark_result(signin(request), benchmark_id)


@router.post("/api/benchmarks/{benchmark_id}/adopt")
def adopt(benchmark_id: str, body: AdoptBody, request: Request):
    return benchmarks.adopt(signin(request), benchmark_id, body.model)


@router.get("/api/proofs/{proof_id}")
def get_proof(proof_id: str, request: Request):
    return proofs.get_proof(proof_id, visitor(request))
