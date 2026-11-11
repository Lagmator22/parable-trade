import hashlib
import importlib
import json
import logging
import time

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool

from parable.config import get_settings
from parable.lab import quota
from parable.db import DB_LOCK, execute, one, rows
from parable.paypal import get_paypal

logger = logging.getLogger("parable.webhooks")

router = APIRouter()

HANDLED_EVENTS = frozenset(
    {
        "PAYMENT.AUTHORIZATION.CREATED",
        "PAYMENT.AUTHORIZATION.VOIDED",
        "PAYMENT.CAPTURE.COMPLETED",
        "PAYMENT.CAPTURE.DENIED",
        "PAYMENT.PAYOUTSBATCH.SUCCESS",
        "PAYMENT.PAYOUTSBATCH.DENIED",
        "PAYMENT.PAYOUTS-ITEM.SUCCEEDED",
        "PAYMENT.PAYOUTS-ITEM.FAILED",
        "PAYMENT.PAYOUTS-ITEM.UNCLAIMED",
    }
)
MAX_BODY_BYTES = 256 * 1024
RECENT_LIMIT = 20
KEEP_UNVERIFIED = 500
WEBHOOKS_PER_MINUTE = 60


def resource_identifier(resource: dict) -> str:
    header = resource.get("batch_header") or {}
    found = resource.get("id") or resource.get("payout_item_id") or header.get("payout_batch_id")
    return str(found or "")


def event_identifier(body: dict, raw: bytes) -> str:
    return str(body.get("id") or "sha-" + hashlib.sha256(raw).hexdigest()[:24])


def parse_event(raw: bytes) -> dict | None:
    if len(raw) > MAX_BODY_BYTES:
        return None
    try:
        body = json.loads(raw)
    except ValueError:
        return None
    return body if isinstance(body, dict) else None


def is_authentic(headers: dict, body: dict) -> bool:
    webhook_id = get_settings().paypal_webhook_id
    if not webhook_id:
        return False
    try:
        return bool(get_paypal().verify_webhook(headers, body, webhook_id))
    except Exception:
        logger.exception("webhook signature check crashed")
        return False


def store_event(event_id: str, body: dict, resource: dict, verified: bool) -> bool:
    with DB_LOCK:
        existing = one("SELECT verified FROM webhook_events WHERE id = ?", (event_id,))
        if existing and (existing["verified"] or not verified):
            return False
        execute(
            "INSERT OR REPLACE INTO webhook_events (id, event_type, resource_id, verified, received_at, body_json)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                event_id,
                str(body.get("event_type", "")),
                resource_identifier(resource),
                int(verified),
                int(time.time()),
                json.dumps(body, sort_keys=True) if verified else "",
            ),
        )
        prune_unverified()
        return True


def prune_unverified() -> None:
    execute("DELETE FROM webhook_events WHERE verified = 0 AND rowid NOT IN"
            " (SELECT rowid FROM webhook_events WHERE verified = 0 ORDER BY received_at DESC, rowid DESC LIMIT ?)",
            (KEEP_UNVERIFIED,))


def dispatch(event_type: str, resource: dict) -> None:
    try:
        market = importlib.import_module("parable.market")
        market.on_webhook(event_type, resource)
    except Exception:
        logger.exception("webhook handler failed for %s", event_type)


def process(raw: bytes, headers: dict) -> dict:
    body = parse_event(raw)
    if body is None:
        return {"ok": False, "stored": False}
    resource = body.get("resource") if isinstance(body.get("resource"), dict) else {}
    verified = is_authentic(headers, body)
    stored = store_event(event_identifier(body, raw), body, resource, verified)
    if stored and verified and body.get("event_type") in HANDLED_EVENTS:
        dispatch(body["event_type"], resource)
    return {"ok": True, "stored": stored, "verified": verified}


@router.post("/paypal/webhook")
async def receive_webhook(request: Request):
    await run_in_threadpool(quota.hit_with_address, "webhook:all", WEBHOOKS_PER_MINUTE, 60)
    raw = await request.body()
    return await run_in_threadpool(process, raw, dict(request.headers))


@router.get("/api/webhooks/recent")
def recent_webhooks():
    events = rows(
        "SELECT id, event_type, resource_id, verified, received_at FROM webhook_events"
        " WHERE verified = 1 ORDER BY received_at DESC, rowid DESC LIMIT ?",
        (RECENT_LIMIT,),
    )
    return [{**event, "verified": bool(event["verified"])} for event in events]
