from fastapi.testclient import TestClient

from lab_support import install_fake, make_bars
from parable import api, ledger, market, proofs, seed
from parable.config import get_settings
from parable.lab import markets
from parable.db import rows


def go_online(monkeypatch) -> None:
    monkeypatch.setenv("MARKETS_OFFLINE", "0")
    get_settings.cache_clear()
    codes = ("BTCUSDT", "ETHUSDT", "PAXGUSDT", "SOLUSDT")
    install_fake(provider_id="binance", intervals=("1s", "1h", "4h", "1d"),
                 bars_by_code={code: make_bars(500, seed=number + 1) for number, code in enumerate(codes)})


def test_offline_seed_uses_bundled_sample_data_only(manager):
    assert seed.seed_demo() == 6
    views = market.list_listings()
    assert len(views) == 6 and {view["mode"] for view in views} == {"instant"}
    assert {view["data"]["source_kind"] for view in views} == {"sample"}
    assert {view["symbol"].partition(":")[0] for view in views} == {"sample"}
    assert all(view["track"] is None for view in views)
    assert not any("Fast Demo" in view["title"] for view in views)
    assert len({view["price_cents"] for view in views}) == 6
    assert all(900 <= view["price_cents"] <= 4900 for view in views)
    assert len(rows("SELECT id FROM sellers WHERE verified = 1")) == 3
    assert ledger.verify()["ok"] is True


def test_seed_proofs_are_real_backtests_that_reproduce(manager):
    seed.seed_demo()
    for view in market.list_listings():
        assert proofs.rerun_listing(view["id"], "v_abcdef0123456789")["match"] is True
        assert view["headline"]["trades"] >= 0 and view["data"]["bars"] >= 30


def test_seed_is_idempotent(manager):
    seed.seed_demo()
    before = ledger.head()
    assert seed.seed_demo() == 0
    assert ledger.head() == before


def test_online_seed_uses_live_symbols_and_adds_the_fast_demo(manager, monkeypatch):
    go_online(monkeypatch)
    assert seed.seed_demo() == 7
    views = {view["title"]: view for view in market.list_listings()}
    live = [view for view in views.values() if view["symbol"].startswith("binance:")]
    assert len(live) == 7 and {view["data"]["source_kind"] for view in live} == {"market"}
    assert all(view["track"] is not None and view["track"]["status"] == "alive" for view in live)
    assert {view["mode"] for view in live} == {"hold", "instant"}
    fast = next(view for title, view in views.items() if title.startswith("Fast Demo"))
    assert (fast["symbol"], fast["interval"], fast["mode"], fast["trial_s"]) == ("binance:BTCUSDT", "1s", "hold", 120)
    assert {"binance:BTCUSDT", "binance:ETHUSDT", "binance:PAXGUSDT", "binance:SOLUSDT"} <= {v["symbol"] for v in live}


def test_online_seed_falls_back_to_samples_when_binance_is_down(manager, monkeypatch):
    go_online(monkeypatch)
    markets.get_provider("binance").fail = True
    assert seed.seed_demo() == 6
    assert {view["data"]["source_kind"] for view in market.list_listings()} == {"sample"}


def test_app_seeds_on_boot_when_enabled(monkeypatch, tmp_path):
    monkeypatch.setenv("PARABLE_DEMO_SEED", "1")
    get_settings.cache_clear()
    with TestClient(api.create_app(tmp_path)) as running:
        assert len(running.get("/api/listings").json()) == 6
