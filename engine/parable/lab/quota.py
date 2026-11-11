import hashlib
import secrets
import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import Callable

from fastapi import Request, Response
from itsdangerous import BadSignature, URLSafeTimedSerializer

from parable import db, guard, identity
from parable.config import get_settings
from parable.errors import LabError

COOKIE = "parable_vid"
COOKIE_SALT = "vid"
COOKIE_MAX_AGE = 365 * 24 * 3600
MAX_KEYS = 10_000
HARD_MAX_KEYS = 20_000
IP_FREE_FACTOR = 2
IP_RATE_FACTOR = 3
LLM_GLOBAL_PER_MINUTE = 120

clock: Callable[[], float] = time.time


def set_clock(fn: Callable[[], float] | None) -> None:
    global clock
    clock = fn or time.time


def today() -> str:
    return datetime.fromtimestamp(clock(), timezone.utc).strftime("%Y-%m-%d")


def serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(identity.secret_key(), salt=COOKIE_SALT)


def cookie_visitor(request: Request) -> str | None:
    token = request.cookies.get(COOKIE)
    if not token:
        return None
    try:
        value = serializer().loads(token, max_age=COOKIE_MAX_AGE)
    except BadSignature:
        return None
    return value if isinstance(value, str) and value.startswith("v_") and len(value) == 18 else None


def ip_visitor(address: str) -> str:
    return "v_" + hashlib.sha256(address.encode()).hexdigest()[:16]


def visitor_id(request: Request, response: Response | None = None) -> str:
    seller = identity.current_seller(request)
    if seller:
        return seller["id"]
    known = cookie_visitor(request)
    if known:
        return known
    if response is None:
        return ip_visitor(guard.client_ip.get())
    fresh = "v_" + secrets.token_hex(8)
    secure = get_settings().public_base_url.startswith("https://")
    response.set_cookie(COOKIE, serializer().dumps(fresh), max_age=COOKIE_MAX_AGE, httponly=True,
                        samesite="lax", secure=secure, path="/")
    return fresh


def free_tries(visitor: str) -> dict:
    limit = get_settings().ai_free_tries_per_day
    row = db.one("SELECT n FROM ai_usage WHERE visitor = ? AND day = ?", (visitor, today()))
    used = row["n"] if row else 0
    return {"limit": limit, "used": used, "remaining": max(0, limit - used)}


def take_free_try(visitor: str) -> None:
    address_key = "ip:" + ip_visitor(guard.client_ip.get())
    with db.DB_LOCK:
        state = free_tries(visitor)
        address_state = free_tries(address_key)
        if state["remaining"] <= 0 or address_state["used"] >= IP_FREE_FACTOR * state["limit"]:
            raise LabError(429, "free_tries_used", "you used today's free AI tries, add your own key to keep going",
                           {"free_tries": state})
        for key in (visitor, address_key):
            db.execute("INSERT INTO ai_usage (visitor, day, n) VALUES (?, ?, 1) "
                       "ON CONFLICT(visitor, day) DO UPDATE SET n = n + 1", (key, today()))


class RateLimiter:
    def __init__(self) -> None:
        self.hits: dict[str, deque] = {}
        self.rules: dict[str, tuple[int, int]] = {}
        self.lock = threading.Lock()

    def live(self, key: str, now: float) -> int:
        window = self.rules[key][1]
        return sum(1 for t in self.hits[key] if t > now - window)

    def drop(self, key: str) -> None:
        self.hits.pop(key, None)
        self.rules.pop(key, None)

    def evict(self, now: float) -> None:
        for key in [k for k, q in self.hits.items() if not q or q[-1] <= now - self.rules[k][1]]:
            self.drop(key)
        if len(self.hits) < MAX_KEYS:
            return
        loose = sorted((k for k in self.hits if self.live(k, now) < self.rules[k][0]), key=lambda k: self.hits[k][-1])
        for key in loose:
            if len(self.hits) < MAX_KEYS:
                return
            self.drop(key)
        if len(self.hits) >= HARD_MAX_KEYS:
            oldest = sorted(self.hits, key=lambda k: self.hits[k][-1])
            for key in oldest[: len(self.hits) - HARD_MAX_KEYS + 1]:
                self.drop(key)

    def hit(self, key: str, limit: int, window_s: int) -> None:
        now = clock()
        with self.lock:
            if key not in self.hits and len(self.hits) >= MAX_KEYS:
                self.evict(now)
            queue = self.hits.setdefault(key, deque())
            self.rules[key] = (limit, window_s)
            while queue and queue[0] <= now - window_s:
                queue.popleft()
            if len(queue) >= limit:
                wait = max(1, int(queue[0] + window_s - now) + 1)
                raise LabError(429, "rate_limited", "too many requests, slow down", {"retry_after": wait})
            queue.append(now)

    def clear(self) -> None:
        with self.lock:
            self.hits.clear()
            self.rules.clear()


limiter = RateLimiter()


def hit_with_address(key: str, limit: int, window_s: int) -> None:
    limiter.hit(key, limit, window_s)
    limiter.hit(f"ip:{guard.client_ip.get()}:{key.partition(':')[0]}", limit * IP_RATE_FACTOR, window_s)


def hit_llm_budget() -> None:
    limiter.hit("llm-global", LLM_GLOBAL_PER_MINUTE, 60)
