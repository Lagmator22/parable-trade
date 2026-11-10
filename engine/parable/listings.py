import json
import secrets
import time

from pydantic import BaseModel, Field

from parable import bot_runner, ledger, referee, runs
from parable.db import DB_LOCK, execute, one, rows
from parable.errors import MarketError
from parable.models import PRESETS, BotRules, fingerprint

MAX_ALIVE_PRACTICE_RUNS = 3
SETTLED_STATUSES = ("created", "cancelled")
PASSED_STATUSES = ("passed", "captured", "paid_out")
FAILED_STATUSES = ("failed", "voided")
HELD_STATUSES = ("authorized", "probation", "passed", "failed")
CAPTURED_STATUSES = ("captured", "paid_out")


class ListingInput(BaseModel):
    title: str = Field(min_length=3, max_length=80)
    pitch: str = Field(default="", max_length=600)
    strategy: str
    brain: str = "rule"
    max_trade_usd: int = Field(ge=1_000_000, le=1_000_000_000)
    max_loss_bps: int = Field(ge=10, le=5000)
    price_cents: int = Field(ge=100, le=50_000)
    probation_s: int = Field(ge=60, le=259_200)
    min_return_bps: int = Field(ge=-500, le=500)


def validate_choices(data: ListingInput) -> None:
    if data.strategy not in PRESETS:
        raise MarketError(f"strategy must be one of {', '.join(PRESETS)}")
    if not bot_runner.available_brains().get(data.brain):
        raise MarketError(f"brain {data.brain} is not available")


def rules_for(data: ListingInput) -> BotRules:
    return BotRules(strategy=data.strategy, brain=data.brain, max_trade_usd=data.max_trade_usd,
                    max_loss_bps=data.max_loss_bps, lease_seconds=data.probation_s)


def create_listing(seller_id: str, data: ListingInput) -> dict:
    validate_choices(data)
    rules = rules_for(data)
    listing_id = "l_" + secrets.token_hex(5)
    code = fingerprint(rules)
    with DB_LOCK:
        execute(
            "INSERT INTO listings (id, seller_id, title, pitch, rules_json, fingerprint, price_cents, probation_s,"
            " min_return_bps, active, created_at) VALUES (?,?,?,?,?,?,?,?,?,1,?)",
            (listing_id, seller_id, data.title.strip(), data.pitch.strip(), rules.model_dump_json(), code,
             data.price_cents, data.probation_s, data.min_return_bps, int(time.time())),
        )
        ledger.append("listing.created", f"listing:{listing_id}", {
            "seller_id": seller_id, "title": data.title.strip(), "fingerprint": code, "rules": rules.model_dump(),
            "price_cents": data.price_cents, "probation_s": data.probation_s, "min_return_bps": data.min_return_bps,
        })
    return get_listing(listing_id)


def listing_row(listing_id: str) -> dict:
    row = one("SELECT * FROM listings WHERE id = ?", (listing_id,))
    if row is None:
        raise MarketError("listing not found", 404)
    return row


def owned_listing(seller_id: str, listing_id: str) -> dict:
    row = listing_row(listing_id)
    if row["seller_id"] != seller_id:
        raise MarketError("this is not your listing", 403)
    return row


def pause_listing(seller_id: str, listing_id: str) -> dict:
    row = owned_listing(seller_id, listing_id)
    if row["active"]:
        with DB_LOCK:
            execute("UPDATE listings SET active = 0 WHERE id = ?", (listing_id,))
            ledger.append("listing.paused", f"listing:{listing_id}", {"seller_id": seller_id})
    return get_listing(listing_id)


def start_practice(seller_id: str, listing_id: str, manager: runs.RunManager | None = None) -> dict:
    row = owned_listing(seller_id, listing_id)
    alive = referee.list_runs(seller_id=seller_id, status="alive", purpose="practice")
    if len(alive) >= MAX_ALIVE_PRACTICE_RUNS:
        raise MarketError(f"at most {MAX_ALIVE_PRACTICE_RUNS} practice runs can be alive at once", 429)
    rules = BotRules.model_validate(json.loads(row["rules_json"]))
    return (manager or runs.get_manager()).start(
        seller_id, rules, "practice", f"{row['title']} (practice)", listing_id=listing_id)


def totals_by_status(listing_id: str | None = None) -> dict[str, dict]:
    where, params = ("WHERE listing_id = ?", (listing_id,)) if listing_id else ("", ())
    found = rows(
        "SELECT status, COUNT(*) AS n, COALESCE(SUM(amount_cents), 0) AS amount, COALESCE(SUM(fee_cents), 0) AS fee"
        f" FROM purchases {where} GROUP BY status", params)
    return {row["status"]: row for row in found}


def totals_by_listing() -> dict[str, dict[str, dict]]:
    grouped: dict[str, dict[str, dict]] = {}
    for row in rows(
            "SELECT listing_id, status, COUNT(*) AS n, COALESCE(SUM(amount_cents), 0) AS amount,"
            " COALESCE(SUM(fee_cents), 0) AS fee FROM purchases GROUP BY listing_id, status"):
        grouped.setdefault(row["listing_id"], {})[row["status"]] = row
    return grouped


def summarize(by_status: dict[str, dict]) -> dict:
    def total(statuses: tuple[str, ...], field: str) -> int:
        return sum(by_status.get(status, {}).get(field, 0) for status in statuses)

    return {
        "purchases": sum(row["n"] for status, row in by_status.items() if status not in SETTLED_STATUSES),
        "passed": total(PASSED_STATUSES, "n"),
        "failed": total(FAILED_STATUSES, "n"),
        "held_cents": total(HELD_STATUSES, "amount"),
        "captured_cents": total(CAPTURED_STATUSES, "amount"),
        "voided_cents": total(("voided",), "amount"),
        "paid_out_cents": total(("paid_out",), "amount") - total(("paid_out",), "fee"),
    }


def seller_summaries() -> dict[str, dict]:
    return {row["id"]: {"id": row["id"], "name": row["name"], "verified": bool(row["verified"])}
            for row in rows("SELECT id, name, verified FROM sellers")}


def unknown_seller(seller_id: str) -> dict:
    return {"id": seller_id, "name": "Unknown seller", "verified": False}


def summary_view(row: dict, sellers: dict[str, dict]) -> dict:
    return {
        "id": row["id"],
        "title": row["title"],
        "pitch": row["pitch"],
        "seller": sellers.get(row["seller_id"]) or unknown_seller(row["seller_id"]),
        "seller_id": row["seller_id"],
        "rules": json.loads(row["rules_json"]),
        "fingerprint": row["fingerprint"],
        "price_cents": row["price_cents"],
        "probation_s": row["probation_s"],
        "min_return_bps": row["min_return_bps"],
        "active": bool(row["active"]),
        "created_at": row["created_at"],
    }


def full_view(row: dict, sellers: dict[str, dict], totals: dict[str, dict]) -> dict:
    return {**summary_view(row, sellers), "seller_record": referee.seller_record(row["seller_id"]),
            "stats": summarize(totals)}


def listing_summary(listing_id: str) -> dict:
    return summary_view(listing_row(listing_id), seller_summaries())


def get_listing(listing_id: str) -> dict:
    row = listing_row(listing_id)
    return full_view(row, seller_summaries(), totals_by_status(listing_id))


def list_listings(include_paused: bool = False) -> list[dict]:
    where = "" if include_paused else "WHERE active = 1"
    found = rows(f"SELECT * FROM listings {where} ORDER BY created_at DESC, id")
    sellers, totals = seller_summaries(), totals_by_listing()
    return [full_view(row, sellers, totals.get(row["id"], {})) for row in found]


def listing_runs(listing_id: str, limit: int = 30) -> list[dict]:
    row = listing_row(listing_id)
    mine = referee.list_runs(seller_id=row["seller_id"], limit=500)
    return [run for run in mine if run["listing_id"] == listing_id][:limit]
