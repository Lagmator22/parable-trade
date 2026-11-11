from lab_support import install_fake, make_bars
from parable import agents, market, proofs, referee, runs
from parable.db import execute, one
from parable.identity import upsert_seller
from parable.lab import markets
from parable.lab.backtest import run_backtest
from parable.lab.templates import template_spec
from parable.models import NewListing
from parable.paypal import get_paypal
from parable.runs import RunManager

USD = 1_000_000
INTERVALS = ("1s", "1m", "1h", "1d")


def make_seller(name: str = "Ada Seller", email: str = "ada@example.com") -> dict:
    return upsert_seller("PAYER-" + email, name, email, True)


def fake_provider():
    try:
        return markets.get_provider("fake")
    except Exception:
        return install_fake(intervals=INTERVALS, bars_by_code={
            "BTCUSDT": make_bars(400), "ETHUSDT": make_bars(400, seed=2)})


def make_proof(owner: dict, symbol: str, interval: str, template: str = "trend", name: str = "Test Agent"):
    if symbol.startswith("fake:"):
        fake_provider()
    spec = template_spec(template, symbol, interval).model_copy(update={"name": name})
    agent = agents.create_agent(owner["id"], name, symbol, interval)
    version = agents.save_version(owner["id"], agent["id"], spec, steps_text="buy dips, sell rips")
    bars = markets.candles(symbol, interval, 400)
    result = run_backtest(spec, bars, symbol=symbol, interval=interval, quote=markets.quote_currency(symbol),
                          source_kind=markets.source_kind(symbol))
    return version, proofs.store_proof("backtest", version["id"], spec, result, bars=bars)


def make_listing(seller: dict | None = None, *, symbol: str = "fake:BTCUSDT", interval: str = "1h",
                 mode: str = "hold", title: str = "Test Agent", price_cents: int = 2000, min_return_bps: int = -50,
                 trial_s: int = 120, max_loss_bps: int = 1000, allow_test_drive: bool = True,
                 template: str = "trend") -> dict:
    owner = seller or make_seller()
    version, proof = make_proof(owner, symbol, interval, template, title)
    created = market.create_listing(owner["id"], NewListing(
        version_id=version["id"], title=title, pitch="A careful agent.", price_cents=price_cents, mode=mode,
        trial_s=trial_s, min_return_bps=min_return_bps, max_loss_bps=max_loss_bps, proof_id=proof["id"],
        allow_test_drive=allow_test_drive))
    return created


def install_manager(interval_s: float = 3600) -> RunManager:
    manager = RunManager(interval_s=interval_s)
    runs.set_manager(manager)
    market.install(manager)
    return manager


def approve_and_confirm(purchase: dict, payer_id: str = "MOCK-BUYER") -> dict:
    get_paypal().approve(purchase["paypal_order_id"], payer_id=payer_id)
    return market.confirm_approval(purchase["purchase_id"], purchase["paypal_order_id"])


def expire_run(run_id: int) -> dict | None:
    execute("UPDATE runs SET expires_at = 0 WHERE id = ?", (run_id,))
    return referee.check(run_id)


def purchase_row(purchase_id: str) -> dict:
    return one("SELECT * FROM purchases WHERE id = ?", (purchase_id,))


def set_headline(listing: dict, **metrics) -> None:
    import json

    row = one("SELECT metrics_json FROM proofs WHERE id = ?", (listing["proof_id"],))
    execute("UPDATE proofs SET metrics_json = ? WHERE id = ?",
            (json.dumps({**json.loads(row["metrics_json"]), **metrics}), listing["proof_id"]))
