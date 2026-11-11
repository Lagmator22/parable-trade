from dataclasses import asdict

from fastapi import APIRouter, File, Form, Request, Response, UploadFile
from pydantic import BaseModel, Field

from parable import agents
from parable.config import get_settings
from parable.errors import LabError
from parable.lab import datasets, jobs, markets
from parable.lab.backtest import data_hash
from parable.routes_ai import router as ai_router
from parable.routes_support import account_of, charge, own_auth, pick_ai, rate, rate_ai, signin, visitor

router = APIRouter()
router.include_router(ai_router)

SEARCH_PER_MINUTE = 60
MAX_CANDLES = 5000


class MapBody(BaseModel):
    draft_id: str = Field(max_length=24)
    mapping: dict[str, str]
    name: str = Field(default="", max_length=60)
    quote: str = Field(default="USD", max_length=5)


class AiMapBody(BaseModel):
    draft_id: str = Field(max_length=24)
    model: str | None = None


def llm_label(auth) -> str:
    return auth.model if auth.provider == "platform" else f"{auth.provider}:{auth.model}"


def public_symbols(found) -> list[dict]:
    return [asdict(i) for i in found if not i.symbol.startswith("upload:")]


def dataset_view(found: dict) -> dict:
    out = {k: v for k, v in found.items() if k != "bars"}
    out.setdefault("bar_count", len(found["bars"]) if "bars" in found else 0)
    return out


@router.get("/api/markets/popular")
def popular(kind: str = "all"):
    return public_symbols(markets.popular(kind))


@router.get("/api/markets/search")
def search(request: Request, response: Response, q: str = "", kind: str = "all"):
    who = visitor(request, response)
    rate(who, "search", SEARCH_PER_MINUTE)
    return public_symbols(markets.search(q[:60], kind))


@router.get("/api/markets/candles")
def candles(request: Request, symbol: str, interval: str, limit: int = 500, start: float | None = None,
            end: float | None = None):
    if not 1 <= limit <= MAX_CANDLES:
        raise LabError(400, "bad_request", f"limit must be 1..{MAX_CANDLES}")
    account = signin(request) if symbol.startswith("upload:") else account_of(request)
    data = agents.resolve_data(account, symbol, interval, limit=limit, start=start, end=end)
    return {"symbol": data["symbol"], "interval": data["interval"], "quote": data["quote"],
            "source_kind": data["source_kind"], "bars": data["bars"], "data_hash": data_hash(data["bars"])}


@router.get("/api/markets/latest")
def latest(request: Request, symbol: str):
    if symbol.startswith("upload:"):
        found = datasets.get_dataset(symbol.partition(":")[2], signin(request))
        last = found["bars"][-1]
        return {"symbol": symbol, "price": last[4], "t": last[0], "quote": found["quote"], "stale": True}
    quote = markets.latest(symbol)
    return {"symbol": quote.symbol, "price": quote.price, "t": quote.t, "quote": quote.quote, "stale": quote.stale}


@router.post("/api/datasets")
async def upload_dataset(request: Request, file: UploadFile = File(...), name: str = Form(""), quote: str = Form("USD")):
    owner = signin(request)
    limit = get_settings().upload_max_bytes
    content = await file.read(limit + 1)
    if len(content) > limit:
        raise LabError(413, "too_large", f"files can be at most {limit // 1_000_000} MB")
    label = name.strip() or (file.filename or "My data").rsplit(".", 1)[0]
    found = datasets.ingest(owner, file.filename or "upload.csv", content, label, quote)
    if found["status"] == "needs_mapping":
        return {**found, "suggestion": None}
    return {"status": "ready", "dataset": dataset_view(found["dataset"]), "warnings": found.get("warnings", [])}


@router.post("/api/datasets/ai-map")
def ai_map(body: AiMapBody, request: Request, response: Response):
    owner = signin(request)
    table = datasets.take_draft(body.draft_id, owner)
    rate_ai(owner)
    auth, platform = pick_ai(owner, body.model, own_auth(request))
    charge(owner, platform)
    return {"mapping": datasets.ai_map_columns(table, auth), "by": llm_label(auth)}


@router.post("/api/datasets/map")
def map_dataset(body: MapBody, request: Request):
    owner = signin(request)
    table = datasets.take_draft(body.draft_id, owner)
    found = datasets.finish_upload(owner, table, body.mapping, body.name or "My data", body.quote)
    return {"status": "ready", "dataset": dataset_view(found["dataset"]), "warnings": found["warnings"]}


@router.get("/api/datasets")
def list_datasets(request: Request):
    return datasets.list_datasets(signin(request))


@router.get("/api/datasets/{dataset_id}")
def get_dataset(dataset_id: str, request: Request):
    return dataset_view(datasets.get_dataset(dataset_id, signin(request)))


@router.delete("/api/datasets/{dataset_id}")
def delete_dataset(dataset_id: str, request: Request):
    datasets.delete_dataset(dataset_id, signin(request))
    return {"ok": True}


@router.get("/api/jobs/{job_id}")
def get_job(job_id: str, request: Request):
    return jobs.get(job_id, visitor(request))
