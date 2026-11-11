import json
import secrets
import time

from parable import db
from parable.config import get_settings
from parable.errors import LabError
from parable.lab import datasets, markets
from parable.lab.consts import INTERVALS, MAX_BARS, MAX_STEPS_CHARS, MIN_BARS
from parable.lab.numeric import canonical_json
from parable.lab.providers.base import clip
from parable.lab.spec import canonical_spec, spec_hash, validate_spec
from parable.models import StrategySpec

ENTITLED = ("captured", "paid_out")
SUMMARY_KEYS = ("id", "n", "name", "summary", "spec_hash", "built_by", "created_at")
AGENT_KEYS = ("id", "name", "symbol", "interval", "status", "latest_version_id", "created_at", "updated_at")


def create_agent(owner_id: str, name: str, symbol: str, interval: str) -> dict:
    name = (name or "").strip()[:60]
    if not name:
        raise LabError(400, "bad_request", "give the agent a name")
    if interval not in INTERVALS:
        raise LabError(400, "bad_request", f"interval must be one of {', '.join(INTERVALS)}")
    head, sep, code = str(symbol).partition(":")
    if not (head and sep and code) or len(symbol) > 64:
        raise LabError(400, "bad_request", "symbols look like provider:CODE")
    with db.DB_LOCK:
        count = db.one("SELECT COUNT(*) AS n FROM agents WHERE owner_id = ?", (owner_id,))["n"]
        if count >= get_settings().max_agents_per_account:
            raise LabError(409, "conflict", "agent limit reached, delete a draft first")
        agent_id = "a_" + secrets.token_hex(5)
        now = int(time.time())
        db.execute("INSERT INTO agents (id, owner_id, name, symbol, interval, status, latest_version_id, created_at,"
                   " updated_at) VALUES (?, ?, ?, ?, ?, 'draft', NULL, ?, ?)",
                   (agent_id, owner_id, name, symbol, interval, now, now))
    return owned_agent(owner_id, agent_id)


def owned_agent(owner_id: str, agent_id: str) -> dict:
    row = db.one("SELECT * FROM agents WHERE id = ?", (agent_id,))
    if row is None:
        raise LabError(404, "not_found", "no such agent")
    if row["owner_id"] != owner_id:
        raise LabError(403, "forbidden", "that agent belongs to someone else")
    return row


def list_agents(owner_id: str) -> list[dict]:
    found = db.rows("SELECT * FROM agents WHERE owner_id = ? ORDER BY created_at DESC, id", (owner_id,))
    counts = {r["agent_id"]: r["n"] for r in db.rows(
        "SELECT agent_id, COUNT(*) AS n FROM agent_versions WHERE agent_id IN "
        "(SELECT id FROM agents WHERE owner_id = ?) GROUP BY agent_id", (owner_id,))}
    return [{**{k: a[k] for k in AGENT_KEYS}, "version_count": counts.get(a["id"], 0)} for a in found]


def version_summaries(agent_id: str) -> list[dict]:
    found = db.rows("SELECT id, n, name, summary, spec_hash, built_by, created_at FROM agent_versions"
                    " WHERE agent_id = ? ORDER BY n DESC", (agent_id,))
    return [{k: v[k] for k in SUMMARY_KEYS} for v in found]


def agent_view(agent: dict, versions: list[dict]) -> dict:
    return {**{k: agent[k] for k in AGENT_KEYS}, "version_count": len(versions),
            "versions": [{k: v[k] for k in SUMMARY_KEYS} for v in versions]}


def agent_detail(owner_id: str, agent_id: str) -> dict:
    agent = owned_agent(owner_id, agent_id)
    return agent_view(agent, version_summaries(agent_id))


def delete_agent(owner_id: str, agent_id: str) -> None:
    agent = owned_agent(owner_id, agent_id)
    if agent["status"] != "draft":
        raise LabError(409, "conflict", "only draft agents can be deleted")
    ids = [v["id"] for v in db.rows("SELECT id FROM agent_versions WHERE agent_id = ?", (agent_id,))]
    with db.DB_LOCK:
        for version_id in ids:
            if db.one("SELECT 1 AS x FROM runs WHERE version_id = ? LIMIT 1", (version_id,)) or db.one(
                    "SELECT 1 AS x FROM listings WHERE version_id = ? LIMIT 1", (version_id,)):
                raise LabError(409, "conflict", "this agent has runs or listings and cannot be deleted")
        for version_id in ids:
            db.execute("DELETE FROM proofs WHERE version_id = ?", (version_id,))
        db.execute("DELETE FROM benchmarks WHERE agent_id = ?", (agent_id,))
        db.execute("DELETE FROM agent_versions WHERE agent_id = ?", (agent_id,))
        db.execute("DELETE FROM agents WHERE id = ?", (agent_id,))


def version_dict(row: dict) -> dict:
    return {**{k: row[k] for k in SUMMARY_KEYS}, "agent_id": row["agent_id"], "steps_text": row["steps_text"] or "",
            "spec": json.loads(row["spec_json"])}


def save_version(owner_id: str, agent_id: str, spec: StrategySpec, steps_text: str = "",
                 built_by: str | None = None) -> dict:
    agent = owned_agent(owner_id, agent_id)
    steps_text = (steps_text or "")[:MAX_STEPS_CHARS]
    if built_by:
        spec = spec.model_copy(update={"built_by": str(built_by)[:80]})
    validate_spec(spec)
    digest = spec_hash(spec)
    with db.DB_LOCK:
        latest = db.one("SELECT * FROM agent_versions WHERE agent_id = ? ORDER BY n DESC LIMIT 1", (agent_id,))
        if latest is not None and latest["spec_hash"] == digest:
            return version_dict(latest)
        n = (latest["n"] if latest else 0) + 1
        if n > get_settings().max_versions_per_agent:
            raise LabError(409, "conflict", "version limit reached for this agent")
        version_id = "v_" + secrets.token_hex(5)
        now = int(time.time())
        db.execute("INSERT INTO agent_versions (id, agent_id, n, name, summary, spec_json, spec_hash, steps_text,"
                   " built_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                   (version_id, agent_id, n, spec.name, spec.summary, canonical_json(canonical_spec(spec)), digest,
                    steps_text, spec.built_by, now))
        db.execute("UPDATE agents SET latest_version_id = ?, updated_at = ? WHERE id = ?", (version_id, now, agent["id"]))
    return owner_version(owner_id, version_id)


def owner_version(owner_id: str, version_id: str) -> dict:
    row = db.one("SELECT * FROM agent_versions WHERE id = ?", (version_id,))
    if row is None:
        raise LabError(404, "not_found", "no such version")
    owned_agent(owner_id, row["agent_id"])
    return version_dict(row)


def agent_version(owner_id: str, agent_id: str, version_id: str) -> dict:
    found = owner_version(owner_id, version_id)
    if found["agent_id"] != agent_id:
        raise LabError(404, "not_found", "no such version")
    return found


def version_owner(version_id: str) -> str | None:
    row = db.one("SELECT a.owner_id FROM agent_versions v JOIN agents a ON a.id = v.agent_id WHERE v.id = ?",
                 (version_id,))
    return row["owner_id"] if row else None


def entitled(account_id: str | None, version_id: str) -> bool:
    if not account_id:
        return False
    if version_owner(version_id) == account_id:
        return True
    marks = ",".join("?" for _ in ENTITLED)
    found = db.one(
        "SELECT 1 AS x FROM purchases p JOIN listings l ON l.id = p.listing_id WHERE p.buyer_id = ? AND "
        f"p.status IN ({marks}) AND (p.version_id = ? OR l.version_id = ?) LIMIT 1",
        (account_id, *ENTITLED, version_id, version_id))
    return found is not None


def resolve_data(account_id: str | None, symbol: str | None, interval: str | None, *, limit: int = 2000,
                 start: float | None = None, end: float | None = None, dataset_id: str | None = None) -> dict:
    if not 1 <= int(limit) <= MAX_BARS:
        raise LabError(400, "bad_request", f"limit must be 1..{MAX_BARS}")
    symbol = (symbol or "").strip() or None
    if dataset_id is None and symbol and symbol.startswith("upload:"):
        dataset_id = symbol.partition(":")[2]
    if dataset_id is not None:
        if symbol and symbol.startswith("upload:") and symbol.partition(":")[2] != dataset_id:
            raise LabError(400, "bad_request", "the symbol and dataset_id disagree")
        if not account_id:
            raise LabError(401, "unauthorized", "sign in to use your uploaded data")
        found = datasets.get_dataset(dataset_id, account_id)
        if interval and interval != found["interval"]:
            raise LabError(400, "bad_request", f"that dataset only has {found['interval']} bars")
        bars = clip(found["bars"], int(limit), start, end)
        meta = {"symbol": found["symbol"], "interval": found["interval"], "quote": found["quote"],
                "source_kind": "creator"}
    else:
        if not symbol or not interval:
            raise LabError(400, "bad_request", "symbol and interval are required")
        bars = markets.closed_candles(symbol, interval, int(limit), start, end)
        meta = {"symbol": symbol, "interval": interval, "quote": markets.quote_currency(symbol),
                "source_kind": markets.source_kind(symbol)}
    if len(bars) < MIN_BARS:
        raise LabError(400, "bad_request", f"only {len(bars)} bars are available, need at least {MIN_BARS}")
    return {**meta, "bars": bars}


def resolve_bars(account_id: str | None, symbol: str, interval: str, *, limit: int = 2000, start=None, end=None,
                 dataset_id: str | None = None) -> tuple[list[list[float]], str]:
    data = resolve_data(account_id, symbol, interval, limit=limit, start=start, end=end, dataset_id=dataset_id)
    return data["bars"], data["source_kind"]


def version_assumptions(version_id: str | None) -> dict | None:
    found = db.one("SELECT spec_json FROM agent_versions WHERE id = ?", (version_id,)) if version_id else None
    if found is None:
        return None
    spec = json.loads(found["spec_json"])
    return {"fee_bps": spec.get("fee_bps"), "slippage_bps": spec.get("slippage_bps")}
