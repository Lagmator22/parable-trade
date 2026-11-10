import hashlib
import logging
import random
from typing import Callable

from parable import bot_runner, prices, referee
from parable.db import execute, one
from parable.identity import upsert_seller
from parable.listings import ListingInput, create_listing
from parable.models import BotRules

log = logging.getLogger("parable.seed")

USD = 1_000_000
START_PRICE = 3000 * prices.PRICE_DECIMALS
TICKS_PER_RUN = 90
EXPIRED_AT = 0

SELLERS = (
    {"key": "priya", "name": "Priya Raman", "email": "priya.raman@example.com"},
    {"key": "tomas", "name": "Tomas Lindqvist", "email": "tomas.lindqvist@example.com"},
    {"key": "dana", "name": "Dana Whitfield", "email": "dana.whitfield@example.com"},
)

LISTINGS = (
    {
        "seller": "priya", "strategy": "mean_revert", "title": "Steady Reverter",
        "pitch": "Trades small and only against sharp moves. Built to stay alive, not to win big.",
        "max_trade_usd": 60 * USD, "max_loss_bps": 300, "price_cents": 1500, "probation_s": 900,
        "min_return_bps": -50, "volatility_bps": 55, "runs": 6,
    },
    {
        "seller": "tomas", "strategy": "momentum", "title": "Trend Rider",
        "pitch": "Follows the price. Rides rallies, steps aside in drops. Mid-sized trades.",
        "max_trade_usd": 150 * USD, "max_loss_bps": 250, "price_cents": 2500, "probation_s": 1800,
        "min_return_bps": 0, "volatility_bps": 34, "runs": 5,
    },
    {
        "seller": "dana", "strategy": "dip_buyer", "title": "Dip Hunter",
        "pitch": "Buys weakness and sells strength with medium-sized trades and a tight stop.",
        "max_trade_usd": 100 * USD, "max_loss_bps": 250, "price_cents": 1900, "probation_s": 1200,
        "min_return_bps": 0, "volatility_bps": 22, "runs": 4,
    },
    {
        "seller": "tomas", "strategy": "yolo", "title": "All-In Gambler",
        "pitch": "Maximum size on every trade. Fast and reckless. Expect it to die often.",
        "max_trade_usd": 400 * USD, "max_loss_bps": 300, "price_cents": 900, "probation_s": 300,
        "min_return_bps": 100, "volatility_bps": 55, "runs": 4,
    },
)


def walk_source(seed: str, volatility_bps: int) -> Callable[[], int]:
    rng = random.Random(int(hashlib.sha256(seed.encode()).hexdigest()[:12], 16))
    state = {"price": START_PRICE}

    def next_price() -> int:
        step = rng.randint(-volatility_bps, volatility_bps)
        state["price"] = state["price"] * (10_000 + step) // 10_000
        return state["price"]

    return next_price


def run_instantly(seller_id: str, listing: dict, rules: BotRules, label: str, volatility_bps: int) -> dict:
    prices.set_price_source(walk_source(label, volatility_bps))
    run = referee.open_run(seller_id, rules, "practice", f"{listing['title']} (practice)", listing_id=listing["id"])
    samples: list[int] = []
    for _ in range(TICKS_PER_RUN):
        bot_runner.take_turn(run["id"], rules, samples)
        if referee.check(run["id"]) is not None:
            break
    if referee.get_run(run["id"])["status"] == "alive":
        execute("UPDATE runs SET expires_at = ? WHERE id = ?", (EXPIRED_AT, run["id"]))
        referee.check(run["id"])
    return referee.get_run(run["id"])


def seed_listing(sellers: dict[str, dict], spec: dict) -> dict:
    owner = sellers[spec["seller"]]
    fields = {key: spec[key] for key in ListingInput.model_fields if key in spec}
    listing = create_listing(owner["id"], ListingInput(brain="rule", **fields))
    rules = BotRules.model_validate(listing["rules"])
    for number in range(spec["runs"]):
        run_instantly(owner["id"], listing, rules, f"{listing['title']}:{number}", spec["volatility_bps"])
    return listing


def seed_sellers() -> dict[str, dict]:
    return {
        seller["key"]: upsert_seller("SEED-" + seller["key"].upper(), seller["name"], seller["email"], True)
        for seller in SELLERS
    }


def seed_demo() -> int:
    if one("SELECT id FROM listings LIMIT 1"):
        return 0
    try:
        sellers = seed_sellers()
        return len([seed_listing(sellers, spec) for spec in LISTINGS])
    finally:
        prices.set_price_source(None)
