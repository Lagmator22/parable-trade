import json
import secrets
import time
from typing import Callable

from parable import agents, db
from parable.errors import LabError
from parable.lab import compiler, llm
from parable.lab.backtest import data_hash, downsample, run_backtest
from parable.config import get_settings
from parable.lab.consts import BACKTEST_CASH, CURVE_MAX, INTERVAL_SECONDS
from parable.lab.llm import AiAuth
from parable.lab.metrics import compute_metrics
from parable.lab.spec import validate_spec
from parable.models import StrategySpec
from parable.proofs import keep_bars, load_bars, store_proof

PLATFORM_HEADS = ("gemini", "gemma", "jev")
PUBLIC_ROW = ("model", "ok", "metrics", "curve", "spec_hash")

Progress = Callable[..., None]


def model_auth(model_id: str, own: AiAuth | None) -> tuple[AiAuth, bool]:
    head, _, name = str(model_id).partition(":")
    if not name:
        raise LabError(400, "bad_request", "model ids look like provider:model")
    if own is not None and head == own.provider:
        return AiAuth(provider=own.provider, model=name, key=own.key), False
    if head in PLATFORM_HEADS:
        match = next((m for m in llm.platform_models() if m.id == model_id), None)
        if match is None or not match.available:
            raise LabError(503, "model_unavailable", "that model is not available right now")
        return AiAuth(provider="platform", model=model_id), True
    if head in llm.PROVIDERS:
        raise LabError(401, "bad_key", f"add your {head} API key to use that model")
    raise LabError(400, "bad_request", "unknown model")


def buy_and_hold(bars: list, interval: str) -> dict:
    closes = [b[4] for b in bars]
    equity = [BACKTEST_CASH * c / closes[0] for c in closes]
    metrics = compute_metrics([b[0] for b in bars], equity, closes, [], INTERVAL_SECONDS[interval], BACKTEST_CASH, True)
    curve = downsample([[b[0], round(e, 6)] for b, e in zip(bars, equity)], CURVE_MAX)
    return {"metrics": {"total_return_pct": metrics["total_return_pct"], "max_drawdown_pct": metrics["max_drawdown_pct"]},
            "curve": curve}


def failed(model: str, error: str) -> dict:
    return {"model": model, "ok": False, "error": error[:120], "summary": "", "metrics": None, "curve": None,
            "spec_hash": None, "built_by": None, "rules": [], "spec": None}


def one_row(model: str, steps: str, symbol: str, interval: str, bars: list, source_kind: str,
            own: AiAuth | None, quote: str) -> dict:
    try:
        auth, _ = model_auth(model, own)
    except LabError as err:
        return failed(model, "needs key" if err.code == "bad_key" else err.detail)
    try:
        built = compiler.compile_steps(steps, symbol, interval, auth)
        result = run_backtest(built.spec, bars, symbol=symbol, interval=interval, quote=quote, source_kind=source_kind)
    except LabError as err:
        return failed(model, err.detail)
    except Exception:
        return failed(model, "the strategy could not be tested")
    return {"model": model, "ok": True, "error": None, "summary": built.summary, "metrics": result["metrics"],
            "curve": result["curve"], "spec_hash": result["spec_hash"], "built_by": built.built_by,
            "rules": [r.model_dump() for r in built.rules], "spec": built.spec.model_dump()}


def run_benchmark(owner_id: str, agent_id: str, steps: str, models: list[str], symbol: str, interval: str,
                  bars: list, source_kind: str, auth: AiAuth | None, progress: Progress,
                  quote: str = "USD") -> dict:
    agents.owned_agent(owner_id, agent_id)
    models = list(dict.fromkeys(models))[:get_settings().benchmark_max_models]
    digest = data_hash(bars)
    benchmark_id = "bm_" + secrets.token_hex(5)
    data = {"symbol": symbol, "interval": interval, "start": bars[0][0], "end": bars[-1][0], "bars": len(bars),
            "data_hash": digest, "source_kind": source_kind, "quote": quote}
    result = {"id": benchmark_id, "agent_id": agent_id, "data": data, "buy_and_hold": buy_and_hold(bars, interval),
              "rows": []}
    for i, model in enumerate(models):
        progress(i / max(1, len(models)), f"testing {model}", {**result, "rows": list(result["rows"])})
        result["rows"].append(one_row(model, steps, symbol, interval, bars, source_kind, auth, quote))
    with db.DB_LOCK:
        keep_bars(bars, digest)
        db.execute("INSERT INTO benchmarks (id, agent_id, owner_id, steps_text, symbol, interval, data_hash,"
                   " result_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                   (benchmark_id, agent_id, owner_id, steps, symbol, interval, digest, json.dumps(result),
                    int(time.time())))
    progress(1.0, "done", result)
    return result


def owned_benchmark(owner_id: str, benchmark_id: str) -> dict:
    row = db.one("SELECT * FROM benchmarks WHERE id = ?", (benchmark_id,))
    if row is None:
        raise LabError(404, "not_found", "no such benchmark")
    if row["owner_id"] != owner_id:
        raise LabError(403, "forbidden", "that benchmark belongs to someone else")
    return row


def benchmark_result(owner_id: str, benchmark_id: str) -> dict:
    return json.loads(owned_benchmark(owner_id, benchmark_id)["result_json"])


def public_benchmark(benchmark_id: str) -> dict | None:
    row = db.one("SELECT result_json FROM benchmarks WHERE id = ?", (benchmark_id,))
    if row is None:
        return None
    full = json.loads(row["result_json"])
    return {"id": full["id"], "data": full["data"], "buy_and_hold": full["buy_and_hold"],
            "rows": [{k: r[k] for k in PUBLIC_ROW} for r in full["rows"]]}


def adopt(owner_id: str, benchmark_id: str, model: str) -> dict:
    row = owned_benchmark(owner_id, benchmark_id)
    full = json.loads(row["result_json"])
    found = next((r for r in full["rows"] if r["model"] == model and r["ok"]), None)
    if found is None:
        raise LabError(404, "not_found", "that model has no result in this benchmark")
    spec = StrategySpec.model_validate(found["spec"])
    validate_spec(spec)
    version = agents.save_version(owner_id, row["agent_id"], spec, row["steps_text"] or "", found["built_by"])
    bars = load_bars(row["data_hash"])
    if bars is not None:
        data = full["data"]
        result = run_backtest(spec, bars, symbol=data["symbol"], interval=data["interval"], quote=data["quote"],
                              source_kind=data["source_kind"])
        store_proof("benchmark", version["id"], spec, result, requester_id=owner_id, bars=bars)
    return version
