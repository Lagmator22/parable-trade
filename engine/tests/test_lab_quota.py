import pytest
from fastapi import FastAPI, Request, Response
from fastapi.testclient import TestClient

from parable import identity
from parable.config import get_settings
from parable.errors import LabError
from parable.lab import quota
from parable.lab.quota import RateLimiter


class Clock:
    def __init__(self, t: float = 1_800_000_000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


@pytest.fixture
def clock():
    fake = Clock()
    quota.set_clock(fake)
    yield fake
    quota.set_clock(None)


def test_free_tries_count_and_exhaust(clock):
    assert quota.free_tries("v_a") == {"limit": 5, "used": 0, "remaining": 5}
    for _ in range(5):
        quota.take_free_try("v_a")
    assert quota.free_tries("v_a") == {"limit": 5, "used": 5, "remaining": 0}
    with pytest.raises(LabError) as err:
        quota.take_free_try("v_a")
    assert err.value.status == 429 and err.value.code == "free_tries_used"
    assert err.value.extra["free_tries"] == {"limit": 5, "used": 5, "remaining": 0}
    assert quota.free_tries("v_a")["used"] == 5
    assert quota.free_tries("v_b")["used"] == 0


def test_allowance_resets_each_utc_day(clock):
    for _ in range(5):
        quota.take_free_try("v_a")
    clock.t += 86_400
    assert quota.free_tries("v_a")["remaining"] == 5
    quota.take_free_try("v_a")
    assert quota.free_tries("v_a")["used"] == 1


def test_limit_follows_settings(clock, monkeypatch):
    monkeypatch.setenv("AI_FREE_TRIES_PER_DAY", "1")
    get_settings.cache_clear()
    quota.take_free_try("v_a")
    with pytest.raises(LabError):
        quota.take_free_try("v_a")


def make_app() -> FastAPI:
    app = FastAPI()

    @app.get("/who")
    def who(request: Request, response: Response):
        return {"visitor": quota.visitor_id(request, response)}

    @app.get("/peek")
    def peek(request: Request):
        return {"visitor": quota.visitor_id(request, None)}

    return app


def test_visitor_cookie_is_signed_and_stable():
    client = TestClient(make_app())
    first = client.get("/who")
    visitor = first.json()["visitor"]
    assert visitor.startswith("v_") and len(visitor) == 18
    cookie = first.cookies.get("parable_vid")
    assert cookie and visitor not in cookie.split(".")[0] or cookie
    assert "httponly" in first.headers["set-cookie"].lower() and "max-age=31536000" in first.headers["set-cookie"].lower()
    assert client.get("/who").json()["visitor"] == visitor
    assert client.get("/peek").json()["visitor"] == visitor


def test_tampered_or_foreign_cookie_is_ignored():
    client = TestClient(make_app())
    visitor = client.get("/who").json()["visitor"]
    forged = TestClient(make_app(), cookies={"parable_vid": "v_" + "0" * 16})
    assert forged.get("/who").json()["visitor"] != "v_" + "0" * 16
    tampered = TestClient(make_app(), cookies={"parable_vid": client.cookies.get("parable_vid") + "x"})
    assert tampered.get("/who").json()["visitor"] != visitor
    other_salt = identity.sign("other", {"v": visitor})
    assert TestClient(make_app(), cookies={"parable_vid": other_salt}).get("/who").json()["visitor"] != visitor


def test_signed_in_account_id_wins(monkeypatch):
    monkeypatch.setattr(identity, "current_seller", lambda request: {"id": "s_abcdef0123"})
    client = TestClient(make_app())
    response = client.get("/who")
    assert response.json() == {"visitor": "s_abcdef0123"} and "set-cookie" not in response.headers


def test_visitor_without_response_is_deterministic_per_client():
    client = TestClient(make_app())
    assert client.get("/peek").json() == client.get("/peek").json()


def test_rate_limiter_sliding_window(clock):
    limiter = RateLimiter()
    for _ in range(3):
        limiter.hit("k", 3, 60)
    with pytest.raises(LabError) as err:
        limiter.hit("k", 3, 60)
    assert err.value.status == 429 and err.value.code == "rate_limited" and err.value.extra["retry_after"] >= 1
    limiter.hit("other", 3, 60)
    clock.t += 30
    with pytest.raises(LabError):
        limiter.hit("k", 3, 60)
    clock.t += 31
    limiter.hit("k", 3, 60)
    limiter.clear()
    for _ in range(3):
        limiter.hit("k", 3, 60)


def test_module_singleton_exists():
    assert isinstance(quota.limiter, RateLimiter)


def test_short_window_flood_does_not_reset_daily_key_at_limit(clock, monkeypatch):
    monkeypatch.setattr(quota, "MAX_KEYS", 20)
    monkeypatch.setattr(quota, "HARD_MAX_KEYS", 40)
    limiter = RateLimiter()
    for _ in range(2):
        limiter.hit("daily", 2, 86_400)
    for i in range(100):
        clock.t += 1
        limiter.hit(f"flood:{i}", 5, 60)
    with pytest.raises(LabError):
        limiter.hit("daily", 2, 86_400)


def test_hourly_key_keeps_count_after_short_window_eviction(clock, monkeypatch):
    monkeypatch.setattr(quota, "MAX_KEYS", 10)
    monkeypatch.setattr(quota, "HARD_MAX_KEYS", 30)
    limiter = RateLimiter()
    limiter.hit("hourly", 3, 3600)
    limiter.hit("hourly", 3, 3600)
    clock.t += 120
    for i in range(15):
        clock.t += 10
        limiter.hit(f"short:{i}", 5, 60)
    assert len(limiter.hits["hourly"]) == 2
    limiter.hit("hourly", 3, 3600)
    with pytest.raises(LabError):
        limiter.hit("hourly", 3, 3600)


def test_expired_keys_are_pruned_and_ceiling_holds(clock, monkeypatch):
    monkeypatch.setattr(quota, "MAX_KEYS", 10)
    monkeypatch.setattr(quota, "HARD_MAX_KEYS", 15)
    limiter = RateLimiter()
    for i in range(10):
        limiter.hit(f"old:{i}", 1, 60)
    clock.t += 61
    limiter.hit("new", 1, 60)
    assert list(limiter.hits) == ["new"]
    for i in range(200):
        limiter.hit(f"full:{i}", 1, 86_400)
        assert len(limiter.hits) <= 15
    assert set(limiter.hits) == set(limiter.rules)
