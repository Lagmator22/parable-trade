from fastapi import APIRouter, Depends, HTTPException

from parable import ledger, referee, runs
from parable.api_support import public_run, require_seller
from parable.db import one, rows
from parable.errors import MarketError
from parable.listings import listing_summary

router = APIRouter()

SELLER_RUN_LIMIT = 50
RUN_ENTRY_LIMIT = 200
LEDGER_MAX = 500


@router.get("/api/runs")
def list_runs(seller: str | None = None, status: str | None = None, purpose: str | None = None):
    return [public_run(run) for run in referee.list_runs(seller_id=seller, status=status, purpose=purpose, limit=100)]


@router.get("/api/runs/{run_id}")
def get_run(run_id: int):
    run = public_run(referee.get_run(run_id))
    return {**run, "entries": ledger.entries(subject=f"run:{run_id}", limit=RUN_ENTRY_LIMIT)}


@router.post("/api/runs/{run_id}/stop")
def stop_run(run_id: int, seller: dict = Depends(require_seller)):
    run = referee.get_run(run_id)
    if run["seller_id"] != seller["id"]:
        raise MarketError("this is not your run", 403)
    if run["purpose"] != "practice":
        raise MarketError("probation runs cannot be stopped by the seller", 403)
    return public_run(runs.get_manager().stop(run_id))


@router.get("/api/sellers/{seller_id}")
def seller_profile(seller_id: str):
    seller = one("SELECT id, name, verified FROM sellers WHERE id = ?", (seller_id,))
    if seller is None:
        raise HTTPException(404, "seller not found")
    listings = rows("SELECT id FROM listings WHERE seller_id = ? AND active = 1 ORDER BY created_at DESC", (seller_id,))
    return {
        "seller": {**seller, "verified": bool(seller["verified"])},
        "record": referee.seller_record(seller_id),
        "runs": [public_run(run) for run in referee.list_runs(seller_id=seller_id, limit=SELLER_RUN_LIMIT)],
        "listings": [listing_summary(row["id"]) for row in listings],
    }


@router.get("/api/ledger")
def ledger_entries(subject: str | None = None, kind: str | None = None, limit: int = 100,
                   before: int | None = None):
    return ledger.entries(subject=subject, kind=kind, limit=max(1, min(limit, LEDGER_MAX)), before_seq=before)


@router.get("/api/ledger/verify")
def verify_ledger():
    return ledger.verify()


@router.post("/api/ledger/tamper-demo")
def tamper_demo():
    return ledger.tamper_demo()
