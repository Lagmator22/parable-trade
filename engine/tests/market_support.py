from parable import market, referee, runs
from parable.db import execute
from parable.identity import upsert_seller
from parable.listings import ListingInput
from parable.paypal import get_paypal
from parable.runs import RunManager

USD = 1_000_000


def make_seller(name: str = "Ada Seller", email: str = "ada@example.com") -> dict:
    return upsert_seller("PAYER-" + email, name, email, True)


def listing_input(**overrides) -> ListingInput:
    base = {
        "title": "Test Bot", "pitch": "A careful bot.", "strategy": "yolo", "brain": "rule",
        "max_trade_usd": 100 * USD, "max_loss_bps": 100, "price_cents": 2000, "probation_s": 120,
        "min_return_bps": -50,
    }
    return ListingInput(**{**base, **overrides})


def make_listing(seller: dict | None = None, **overrides) -> dict:
    owner = seller or make_seller()
    return market.create_listing(owner["id"], listing_input(**overrides))


def install_manager(interval_s: float = 3600) -> RunManager:
    manager = RunManager(interval_s=interval_s)
    runs.set_manager(manager)
    market.install(manager)
    return manager


def approve_and_confirm(purchase: dict) -> dict:
    get_paypal().approve(purchase["paypal_order_id"])
    return market.confirm_approval(purchase["purchase_id"], purchase["paypal_order_id"])


def expire_run(run_id: int) -> dict | None:
    execute("UPDATE runs SET expires_at = 0 WHERE id = ?", (run_id,))
    return referee.check(run_id)
