import hashlib
import hmac
import importlib
import secrets
import time
from urllib.parse import parse_qs

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from itsdangerous import BadSignature, URLSafeTimedSerializer

from parable.config import get_settings, paypal_mode
from parable.db import DB_LOCK, execute, one
from parable.identity_pages import mock_login_page
from parable.paypal import PayPalError, get_paypal, is_mock

SESSION_COOKIE = "parable_session"
STATE_COOKIE = "parable_oauth_state"
SESSION_SALT = "parable.session"
STATE_SALT = "parable.oauth-state"
SESSION_MAX_AGE = 7 * 24 * 3600
STATE_MAX_AGE = 600
DEFAULT_NAME = "Demo Seller"
DEFAULT_EMAIL = "demo.seller@example.com"
HOME_AFTER_LOGIN = "/#sell"
MAX_NAME_LENGTH = 60
MAX_FORM_BYTES = 8192

router = APIRouter()
fallback_secret = secrets.token_hex(32)


def secret_key() -> str:
    return get_settings().session_secret or fallback_secret


def sign(salt: str, payload: dict) -> str:
    return URLSafeTimedSerializer(secret_key(), salt=salt).dumps(payload)


def unsign(salt: str, token: str | None, max_age: int) -> dict | None:
    if not token:
        return None
    try:
        payload = URLSafeTimedSerializer(secret_key(), salt=salt).loads(token, max_age=max_age)
    except BadSignature:
        return None
    return payload if isinstance(payload, dict) else None


def set_cookie(response: Response, name: str, value: str, max_age: int) -> None:
    secure = get_settings().public_base_url.startswith("https://")
    response.set_cookie(name, value, max_age=max_age, httponly=True, samesite="lax", secure=secure, path="/")


def redirect(location: str) -> RedirectResponse:
    return RedirectResponse(location, status_code=302)


def mask_email(email: str | None) -> str:
    local, _, domain = (email or "").partition("@")
    return f"{local[:1]}***@{domain}" if domain else ""


def record_joined(seller: dict) -> None:
    ledger = importlib.import_module("parable.ledger")
    ledger.append("seller.joined", f"seller:{seller['id']}", {"name": seller["name"], "verified": bool(seller["verified"])})


def upsert_seller(payer_id: str, name: str, email: str, verified: bool) -> dict:
    with DB_LOCK:
        existing = one("SELECT * FROM sellers WHERE paypal_payer_id = ?", (payer_id,))
        if existing:
            return refresh_seller(existing, name, email, verified)
        seller_id = "s_" + secrets.token_hex(5)
        execute(
            "INSERT INTO sellers (id, paypal_payer_id, name, email, verified, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (seller_id, payer_id, name, email, int(verified), int(time.time())),
        )
        seller = one("SELECT * FROM sellers WHERE id = ?", (seller_id,))
        record_joined(seller)
        return seller


def refresh_seller(existing: dict, name: str, email: str, verified: bool) -> dict:
    merged = {
        "name": name or existing["name"],
        "email": email or existing["email"],
        "verified": int(verified),
    }
    execute(
        "UPDATE sellers SET name = ?, email = ?, verified = ? WHERE id = ?",
        (merged["name"], merged["email"], merged["verified"], existing["id"]),
    )
    return {**existing, **merged}


def current_seller(request: Request) -> dict | None:
    payload = unsign(SESSION_SALT, request.cookies.get(SESSION_COOKIE), SESSION_MAX_AGE)
    if not payload or not payload.get("seller_id"):
        return None
    return one("SELECT * FROM sellers WHERE id = ?", (payload["seller_id"],))


def sign_in(response: Response, seller: dict) -> None:
    set_cookie(response, SESSION_COOKIE, sign(SESSION_SALT, {"seller_id": seller["id"]}), SESSION_MAX_AGE)


def state_matches(request: Request, state: str) -> bool:
    payload = unsign(STATE_SALT, request.cookies.get(STATE_COOKIE), STATE_MAX_AGE)
    expected = str((payload or {}).get("state", ""))
    return bool(state) and bool(expected) and hmac.compare_digest(expected, state)


def failure(status: int, detail: str) -> JSONResponse:
    return JSONResponse({"detail": detail}, status_code=status)


@router.get("/paypal/login")
def paypal_login():
    if is_mock():
        return redirect("/paypal/mock-login")
    state = secrets.token_urlsafe(24)
    redirect_uri = get_settings().public_base_url.rstrip("/") + "/paypal/callback"
    response = redirect(get_paypal().oauth_authorize_url(state, redirect_uri))
    set_cookie(response, STATE_COOKIE, sign(STATE_SALT, {"state": state}), STATE_MAX_AGE)
    return response


@router.get("/paypal/callback")
def paypal_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    if error:
        return redirect(HOME_AFTER_LOGIN)
    if not state_matches(request, state):
        return failure(400, "invalid state")
    if not code:
        return failure(400, "missing code")
    try:
        client = get_paypal()
        info = client.userinfo(client.exchange_code(code))
    except PayPalError as problem:
        return failure(502, f"paypal: {problem.name}")
    if not info.get("payer_id"):
        return failure(502, "paypal: MISSING_PAYER_ID")
    seller = upsert_seller(info["payer_id"], info["name"], info["email"], info["verified"])
    response = redirect(HOME_AFTER_LOGIN)
    sign_in(response, seller)
    response.delete_cookie(STATE_COOKIE, path="/")
    return response


@router.get("/paypal/mock-login")
def mock_login_form():
    if not is_mock():
        return failure(404, "mock sign-in is disabled")
    return HTMLResponse(mock_login_page(DEFAULT_NAME, DEFAULT_EMAIL))


async def read_form(request: Request) -> dict[str, str]:
    body = (await request.body())[:MAX_FORM_BYTES].decode("utf-8", errors="replace")
    return {key: values[0] for key, values in parse_qs(body).items()}


@router.post("/paypal/mock-login")
async def mock_login_submit(request: Request):
    if not is_mock():
        return failure(404, "mock sign-in is disabled")
    form = await read_form(request)
    name = form.get("name", "").strip()[:MAX_NAME_LENGTH]
    email = form.get("email", "").strip().lower()
    if not name or "@" not in email:
        page = mock_login_page(name, email, "Enter a name and a valid email.")
        return HTMLResponse(page, status_code=400)
    payer_id = "MOCK-" + hashlib.sha256(email.encode()).hexdigest()[:16]
    seller = await run_in_threadpool(upsert_seller, payer_id, name, email, True)
    response = redirect(HOME_AFTER_LOGIN)
    sign_in(response, seller)
    return response


@router.get("/api/me")
def me(request: Request):
    seller = current_seller(request)
    visible = None
    if seller:
        visible = {
            "id": seller["id"],
            "name": seller["name"],
            "verified": bool(seller["verified"]),
            "email_masked": mask_email(seller["email"]),
        }
    mode = "mock" if is_mock() else paypal_mode()
    return {"seller": visible, "paypal_mode": mode}


@router.post("/api/logout")
def logout():
    response = JSONResponse({"ok": True})
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response
