from fastapi.testclient import TestClient

from parable import api, db, ledger, prices, referee, seed
from parable.config import get_settings
from parable.db import rows


def test_seed_creates_sellers_listings_and_truthful_records():
    assert seed.seed_demo() == 4
    assert len(rows("SELECT id FROM sellers WHERE verified = 1")) == 3
    listings = rows("SELECT * FROM listings")
    assert len(listings) == 4 and len({row["fingerprint"] for row in listings}) == 4
    assert len({row["price_cents"] for row in listings}) == 4
    for listing in listings:
        finished = [run for run in referee.list_runs(limit=500) if run["listing_id"] == listing["id"]]
        assert 3 <= len(finished) <= 6
        assert all(run["status"] == "dead" and run["purpose"] == "practice" for run in finished)
    causes = {run["cause"] for run in referee.list_runs(limit=500)}
    assert causes == {"expired", "loss_limit"}
    assert ledger.verify()["ok"] is True
    ended = ledger.entries(kind="run.ended", limit=500)
    assert len(ended) == len(referee.list_runs(limit=500))


def test_seed_is_skipped_when_listings_exist():
    seed.seed_demo()
    before = ledger.head()
    assert seed.seed_demo() == 0
    assert ledger.head() == before


def test_seed_restores_the_configured_price_source():
    seed.seed_demo()
    first = prices.price()
    assert 100 * prices.PRICE_DECIMALS < first < 100_000 * prices.PRICE_DECIMALS
    assert prices._state.override is None


def outcomes() -> list[tuple]:
    found = referee.list_runs(limit=500)
    return [(run["name"], run["cause"], run["pnl_bps"], run["trades"]) for run in reversed(found)]


def test_seed_is_deterministic():
    seed.seed_demo()
    first = outcomes()
    db.reset_db(":memory:")
    seed.seed_demo()
    assert outcomes() == first
    assert len(first) == sum(spec["runs"] for spec in seed.LISTINGS)


def test_app_seeds_on_boot_when_enabled(monkeypatch, tmp_path):
    monkeypatch.setenv("PARABLE_DEMO_SEED", "1")
    get_settings.cache_clear()
    with TestClient(api.create_app(tmp_path)) as running:
        assert len(running.get("/api/listings").json()) == 4
