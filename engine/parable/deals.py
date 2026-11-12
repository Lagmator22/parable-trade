import json
import re
import secrets
import threading
import time

from parable import identity, ledger
from parable.db import DB_LOCK, execute, one, rows
from parable.deal_rules import (BUILD_SYSTEM, CHECK_SYSTEM, accept_built, accept_checked, build_prompt, check_prompt,
                                clean_checklist, fallback_checklist, merge_verdict, rule_result)
from parable.errors import LabError
from parable.lab import llm
from parable.lab.llm import AiAuth
from parable.paypal import PayPalError, get_paypal, is_mock
from parable.purchases import fee_for

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_ATTEMPTS = 3
MAX_DEALS_PER_CLIENT = 20
ERROR_LIMIT = 200
_ORIGINAL_CHAT_JSON = llm.chat_json

_locks: dict[str, threading.RLock] = {}
_locks_guard = threading.Lock()


def deal_lock(deal_id: str) -> threading.RLock:
    with _locks_guard:
        return _locks.setdefault(deal_id, threading.RLock())


def load_deal(deal_id: str) -> dict:
    row = one("SELECT * FROM deals WHERE id = ?", (deal_id,))
    if row is None:
        raise LabError(404, "not_found", "deal not found")
    return row


def owned_deal(deal_id: str, client_id: str) -> dict:
    row = load_deal(deal_id)
    if row["client_id"] != client_id:
        raise LabError(404, "not_found", "deal not found")
    return row


def update_deal(deal_id: str, **fields) -> None:
    fields["updated_at"] = int(time.time())
    assignments = ", ".join(f"{col} = ?" for col in fields)
    execute(f"UPDATE deals SET {assignments} WHERE id = ?", (*fields.values(), deal_id))


def _default_title(brief: str) -> str:
    first = re.split(r"[.!?\n]+", (brief or "").strip())[0].strip()
    if len(first) > 60:
        first = first[:57].rstrip() + "..."
    return first if len(first) >= 3 else "Freelance deal"


def _auth_label(auth: AiAuth) -> str:
    return auth.model if auth.provider == "platform" else f"{auth.provider}:{auth.model}"


def platform_auth() -> AiAuth | None:
    for info in llm.platform_models():
        if info.available:
            return AiAuth(provider="platform", model=info.id)
    if llm.chat_json is not _ORIGINAL_CHAT_JSON:
        return AiAuth(provider="platform", model=f"gemini:{llm.DEFAULT_GEMINI}")
    return None


def validate_brief(brief: str) -> str:
    cleaned = (brief or "").strip()
    if not (20 <= len(cleaned) <= 4000):
        raise LabError(422, "invalid_spec", "brief must be 20 to 4000 characters")
    return cleaned


def build_checklist(brief: str, auth: AiAuth | None) -> dict:
    cleaned_brief = validate_brief(brief)
    if auth is not None:
        try:
            reply = llm.chat_json(auth, build_prompt(cleaned_brief), system=BUILD_SYSTEM, timeout=30)
            items = accept_built(reply)
            raw_title = str(reply.get("title") or "").strip()[:60] if isinstance(reply, dict) else ""
            title = raw_title if len(raw_title) >= 3 else _default_title(cleaned_brief)
            return {"title": title, "items": items, "built_by": _auth_label(auth)}
        except Exception:
            pass
    return {"title": _default_title(cleaned_brief), "items": fallback_checklist(cleaned_brief), "built_by": "rules"}


def create_deal(client_id: str, title: str, brief: str, checklist: list[dict], amount_cents: int,
                freelancer_email: str, built_by: str | None = None) -> dict:
    cleaned_title = (title or "").strip()
    if not (3 <= len(cleaned_title) <= 80):
        raise LabError(422, "invalid_spec", "title must be 3 to 80 characters")
    cleaned_brief = validate_brief(brief)
    cleaned_items = clean_checklist(checklist)
    if isinstance(amount_cents, bool) or not isinstance(amount_cents, int) or not (100 <= amount_cents <= 50000):
        raise LabError(422, "invalid_spec", "amount_cents must be between 100 and 50000")
    email = (freelancer_email or "").strip().lower()
    if not email or len(email) > 120 or not EMAIL_RE.match(email):
        raise LabError(422, "invalid_spec", "freelancer_email is not valid")
    count = (one("SELECT COUNT(*) AS n FROM deals WHERE client_id = ?", (client_id,)) or {}).get("n", 0)
    if count >= MAX_DEALS_PER_CLIENT:
        raise LabError(429, "limit_reached", "maximum of 20 deals per client reached")
    deal_id = "dl_" + secrets.token_hex(5)
    share_token = secrets.token_urlsafe(18)
    fee_cents = fee_for(amount_cents)
    maker = (built_by or "rules").strip()[:80] or "rules"
    now = int(time.time())
    with DB_LOCK:
        execute(
            "INSERT INTO deals (id, client_id, title, brief, checklist_json, amount_cents, fee_cents,"
            " freelancer_email, share_token, status, attempts, built_by, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,'draft',0,?,?,?)",
            (deal_id, client_id, cleaned_title, cleaned_brief, json.dumps(cleaned_items), amount_cents, fee_cents,
             email, share_token, maker, now, now))
        ledger.append("deal.created", f"deal:{deal_id}", {
            "amount_cents": amount_cents, "items": len(cleaned_items), "built_by": maker})
    return load_deal(deal_id)


def start_order(deal: dict, base_url: str) -> dict:
    with deal_lock(deal["id"]):
        current = load_deal(deal["id"])
        if current["status"] != "draft":
            raise LabError(409, "conflict", "deal is not in draft status")
        if current["paypal_order_id"]:
            url = get_paypal().order_approve_url(current["paypal_order_id"])
            return {"paypal_order_id": current["paypal_order_id"], "approve_url": url}
        deal_url = f"{base_url.rstrip('/')}/#deal/{current['id']}"
        order = get_paypal().create_order(
            current["amount_cents"], f"Parable deal: {current['title']}"[:127], current["id"],
            deal_url, deal_url, intent="AUTHORIZE")
        update_deal(current["id"], paypal_order_id=order["id"])
        return {"paypal_order_id": order["id"], "approve_url": order["approve_url"]}


def fund(deal: dict, order_id: str, payer: dict) -> dict:
    with deal_lock(deal["id"]):
        current = load_deal(deal["id"])
        if not order_id or order_id != current["paypal_order_id"]:
            raise LabError(400, "bad_request", "order_id does not belong to this deal")
        if current["status"] == "funded":
            return current
        if current["status"] != "draft":
            raise LabError(409, "conflict", f"cannot fund deal in {current['status']} status")
        if is_mock():
            get_paypal().approve(
                order_id, payer_email=payer.get("email") or "mock.buyer@example.com",
                payer_id=payer.get("payer_id") or "MOCK-BUYER")
        auth = get_paypal().authorize_order(order_id)
        with DB_LOCK:
            update_deal(current["id"], status="funded", paypal_authorization_id=auth["authorization_id"], error=None)
            ledger.append("deal.funded", f"deal:{current['id']}", {"amount_cents": current["amount_cents"]})
        return load_deal(current["id"])


def _run_ai_check(checklist: list[dict], work_text: str, ai_ids: list[str]) -> list[dict] | None:
    auth = platform_auth()
    if auth is None:
        return None
    prompt = check_prompt(checklist, work_text)
    for _ in (1, 2):
        try:
            reply = llm.chat_json(auth, prompt, system=CHECK_SYSTEM, timeout=45)
        except Exception:
            continue
        checked = accept_checked(reply, ai_ids)
        if checked is not None:
            return checked
    return None


def check(deal: dict) -> dict:
    with deal_lock(deal["id"]):
        current = load_deal(deal["id"])
        checklist = json.loads(current["checklist_json"])
        work_text = current.get("work_text") or ""
        rules = [res for item in checklist if (res := rule_result(item, work_text)) is not None]
        ai_ids = [item["id"] for item in checklist if item.get("kind", "ai") == "ai"]
        ai_results = _run_ai_check(checklist, work_text, ai_ids) if ai_ids else []
        if ai_results is None:
            verdict = merge_verdict(checklist, rules, {})
            verdict["passed"] = False
            with DB_LOCK:
                update_deal(current["id"], verdict_json=json.dumps(verdict, sort_keys=True), error="checker unavailable")
            return load_deal(current["id"])
        verdict = merge_verdict(checklist, rules, ai_results)
        passed_items = sum(1 for item in verdict["items"] if item["pass"])
        with DB_LOCK:
            update_deal(current["id"], verdict_json=json.dumps(verdict, sort_keys=True), error=None)
            ledger.append("deal.checked", f"deal:{current['id']}", {
                "attempt": current["attempts"], "passed": verdict["passed"],
                "passed_items": passed_items, "total_items": len(verdict["items"])})
        updated = load_deal(current["id"])
        return release(updated, by="agent") if verdict["passed"] else updated


def submit(deal: dict, work_text: str, work_url: str | None = None) -> dict:
    text = (work_text or "").strip()
    if not (1 <= len(text) <= 20000):
        raise LabError(422, "invalid_spec", "work_text must be 1 to 20000 characters")
    url = (work_url or "").strip()
    if url and (len(url) > 300 or not url.startswith("https://")):
        raise LabError(422, "invalid_spec", "work_url must start with https:// and be at most 300 characters")
    with deal_lock(deal["id"]):
        current = load_deal(deal["id"])
        if current["status"] not in ("funded", "submitted"):
            raise LabError(409, "conflict", f"cannot submit work in {current['status']} status")
        if current["attempts"] >= MAX_ATTEMPTS:
            raise LabError(409, "conflict", "maximum of 3 attempts reached")
        attempt = current["attempts"] + 1
        with DB_LOCK:
            update_deal(current["id"], work_text=text, work_url=url or None, attempts=attempt, status="submitted", error=None)
            ledger.append("deal.submitted", f"deal:{current['id']}", {"attempt": attempt})
        return check(load_deal(current["id"]))


def _paypal_err(err: Exception) -> str:
    if isinstance(err, PayPalError):
        return f"{err.name}: {err.detail}"[:ERROR_LIMIT]
    return f"payment error: {type(err).__name__}"[:ERROR_LIMIT]


def release(deal: dict, by: str = "client") -> dict:
    with deal_lock(deal["id"]):
        current = load_deal(deal["id"])
        if current["status"] == "released":
            return current
        if current["status"] not in ("funded", "submitted", "error"):
            raise LabError(409, "conflict", f"cannot release deal in {current['status']} status")
        payout_cents = current["amount_cents"] - current["fee_cents"]
        try:
            if not current["paypal_capture_id"]:
                cap = get_paypal().capture_authorization(
                    current["paypal_authorization_id"], current["amount_cents"], current["id"])
                update_deal(current["id"], paypal_capture_id=cap["capture_id"], error=None)
                current = load_deal(current["id"])
            if not current["paypal_payout_batch_id"]:
                pay = get_paypal().create_payout(
                    f"{current['id']}-payout", current["freelancer_email"], payout_cents,
                    f"Parable deal {current['title']}"[:200])
                update_deal(current["id"], paypal_payout_batch_id=pay["payout_batch_id"], payout_status=pay["batch_status"])
            with DB_LOCK:
                update_deal(current["id"], status="released", error=None)
                ledger.append("deal.released", f"deal:{current['id']}", {
                    "amount_cents": current["amount_cents"], "payout_cents": payout_cents, "by": by})
        except Exception as err:
            update_deal(current["id"], status="error", error=_paypal_err(err))
        return load_deal(current["id"])


def refund(deal: dict) -> dict:
    with deal_lock(deal["id"]):
        current = load_deal(deal["id"])
        if current["status"] not in ("funded", "submitted", "error") or current["paypal_capture_id"]:
            raise LabError(409, "conflict", "cannot refund this deal")
        get_paypal().void_authorization(current["paypal_authorization_id"])
        with DB_LOCK:
            update_deal(current["id"], status="returned", error=None)
            ledger.append("deal.returned", f"deal:{current['id']}", {"amount_cents": current["amount_cents"]})
        return load_deal(current["id"])


def public_view(deal: dict) -> dict:
    return {
        "id": deal["id"], "title": deal["title"], "status": deal["status"],
        "amount_cents": deal["amount_cents"], "fee_cents": deal["fee_cents"],
        "payout_cents": deal["amount_cents"] - deal["fee_cents"],
        "checklist": json.loads(deal["checklist_json"]),
        "verdict": json.loads(deal["verdict_json"]) if deal["verdict_json"] else None,
        "attempts": deal["attempts"], "attempts_left": max(0, MAX_ATTEMPTS - deal["attempts"]),
        "built_by": deal["built_by"], "created_at": deal["created_at"],
        "updated_at": deal["updated_at"], "error": deal["error"]}


def party_view(deal: dict) -> dict:
    return {**public_view(deal), "brief": deal["brief"], "work_text": deal["work_text"], "work_url": deal["work_url"],
            "freelancer_email_masked": identity.mask_email(deal["freelancer_email"]), "payout_status": deal["payout_status"]}


def client_view(deal: dict) -> dict:
    return {**party_view(deal), "share_token": deal["share_token"], "freelancer_email": deal["freelancer_email"],
            "paypal_order_id": deal["paypal_order_id"]}


def timeline(deal_id: str) -> list[dict]:
    found = ledger.entries(subject=f"deal:{deal_id}", limit=50)
    return [{"seq": r["seq"], "at": r["at"], "kind": r["kind"], "data": r["data"], "hash": r["hash"]} for r in reversed(found)]


def list_for_client(client_id: str) -> list[dict]:
    found = rows("SELECT * FROM deals WHERE client_id = ? ORDER BY created_at DESC, rowid DESC", (client_id,))
    return [{**public_view(d), "share_token": d["share_token"]} for d in found]
