import base64
import contextvars
import hashlib
import re

from parable.config import get_settings
from parable.errors import LabError

MAX_BODY_BYTES = 1_000_000
MAX_UPLOAD_BODY_BYTES = 6_500_000
UPLOAD_PATH = "/api/datasets"
WEBHOOK_PATH = "/paypal/webhook"
MAX_WEBHOOK_BODY_BYTES = 262_144
INLINE_SCRIPT = re.compile(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", re.S)
PAYPAL_HOSTS = "https://www.paypal.com https://www.sandbox.paypal.com https://*.paypal.com https://*.paypalobjects.com"

client_ip: contextvars.ContextVar[str] = contextvars.ContextVar("client_ip", default="unknown")


def script_hashes(html: str) -> list[str]:
    found = []
    for body in INLINE_SCRIPT.findall(html):
        digest = base64.b64encode(hashlib.sha256(body.encode()).digest()).decode()
        found.append(f"'sha256-{digest}'")
    return found


def content_security_policy(hashes: list[str]) -> str:
    scripts = " ".join(["'self'", *hashes, PAYPAL_HOSTS])
    return "; ".join([
        "default-src 'self'",
        f"script-src {scripts}",
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
        "font-src 'self' https://fonts.gstatic.com data:",
        f"img-src 'self' data: {PAYPAL_HOSTS}",
        f"connect-src 'self' {PAYPAL_HOSTS}",
        f"frame-src {PAYPAL_HOSTS}",
        "frame-ancestors 'none'",
        "base-uri 'self'",
        f"form-action 'self' {PAYPAL_HOSTS}",
        "object-src 'none'",
    ])


def header_value(scope: dict, name: bytes) -> str:
    for key, value in scope.get("headers", []):
        if key == name:
            return value.decode("latin-1")
    return ""


def resolve_client_ip(scope: dict) -> str:
    peer = (scope.get("client") or ("unknown", 0))[0]
    if not get_settings().trust_proxy:
        return peer
    forwarded = [part.strip() for part in header_value(scope, b"x-forwarded-for").split(",") if part.strip()]
    return forwarded[-1] if forwarded else peer


def body_limit(path: str) -> int:
    if path == UPLOAD_PATH:
        return MAX_UPLOAD_BODY_BYTES
    return MAX_WEBHOOK_BODY_BYTES if path == WEBHOOK_PATH else MAX_BODY_BYTES


class TooLarge(LabError):
    def __init__(self) -> None:
        super().__init__(413, "too_large", "request body too large")


class RequestGuard:
    def __init__(self, app, hashes: list[str] | None = None) -> None:
        self.app = app
        self.policy = content_security_policy(hashes or [])

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        token = client_ip.set(resolve_client_ip(scope))
        try:
            await self.guarded(scope, receive, send)
        finally:
            client_ip.reset(token)

    async def guarded(self, scope, receive, send):
        limit = body_limit(scope["path"])
        declared = header_value(scope, b"content-length")
        if declared.isdigit() and int(declared) > limit:
            await self.reject(send)
            return
        seen = 0
        started = False

        async def counted():
            nonlocal seen
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > limit:
                    raise TooLarge()
            return message

        async def tracked(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                message = {**message, "headers": [*message.get("headers", []), *self.security_headers()]}
            await send(message)

        try:
            await self.app(scope, counted, tracked)
        except TooLarge:
            if not started:
                await self.reject(send)

    def security_headers(self) -> list[tuple[bytes, bytes]]:
        headers = [
            (b"content-security-policy", self.policy.encode()),
            (b"x-content-type-options", b"nosniff"),
            (b"x-frame-options", b"DENY"),
            (b"referrer-policy", b"strict-origin-when-cross-origin"),
            (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
        ]
        if get_settings().public_base_url.startswith("https://"):
            headers.append((b"strict-transport-security", b"max-age=31536000; includeSubDomains"))
        return headers

    async def reject(self, send):
        body = b'{"detail":"request body too large"}'
        headers = [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode()),
                   *self.security_headers()]
        await send({"type": "http.response.start", "status": 413, "headers": headers})
        await send({"type": "http.response.body", "body": body})
