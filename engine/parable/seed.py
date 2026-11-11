import logging

from parable import agents, proofs
from parable.config import get_settings, paypal_mode
from parable.db import one
from parable.identity import upsert_seller
from parable.lab import markets
from parable.lab.backtest import run_backtest
from parable.lab.consts import INTERVAL_SECONDS, MIN_BARS
from parable.lab.templates import template_spec
from parable.listings import create_listing
from parable.models import NewListing

log = logging.getLogger("parable.seed")

SELLERS = (
    {"key": "priya", "name": "Priya Raman", "email": "priya.raman@example.com"},
    {"key": "tomas", "name": "Tomas Lindqvist", "email": "tomas.lindqvist@example.com"},
    {"key": "dana", "name": "Dana Whitfield", "email": "dana.whitfield@example.com"},
)

ASSETS = {
    "btc": {"live": ("binance:BTCUSDT", "1h"), "sample": ("sample:BTCUSDT", "1h")},
    "eth": {"live": ("binance:ETHUSDT", "4h"), "sample": ("sample:ETHUSDT", "1d")},
    "gold": {"live": ("binance:PAXGUSDT", "1h"), "sample": ("sample:PAXGUSDT", "1d")},
    "sol": {"live": ("binance:SOLUSDT", "1h"), "sample": ("sample:SOLUSDT", "1h")},
    "eur": {"live": ("fx:EURUSD", "1d"), "sample": ("sample:EURUSD", "1d")},
}

AGENTS = (
    {"seller": "priya", "asset": "btc", "template": "trend", "title": "Bitcoin Trend Rider", "price_cents": 2900,
     "pitch": "Follows the Bitcoin trend with a stop loss. Every number is reproducible from its proof."},
    {"seller": "priya", "asset": "eth", "template": "rsi", "title": "Ether RSI Swing", "price_cents": 1900,
     "pitch": "Buys oversold Ether and sells when momentum recovers."},
    {"seller": "tomas", "asset": "gold", "template": "mean_revert", "title": "Gold Mean Reverter",
     "price_cents": 3900, "pitch": "Fades stretched moves in tokenised gold and waits for the average to pull back."},
    {"seller": "tomas", "asset": "sol", "template": "breakout", "title": "Solana Breakout", "price_cents": 1400,
     "pitch": "Enters when Solana breaks its recent high and rides it with a trailing exit."},
    {"seller": "dana", "asset": "btc", "template": "macd", "title": "Bitcoin MACD Pulse", "price_cents": 4900,
     "pitch": "Trades Bitcoin MACD momentum crossovers with fixed risk."},
    {"seller": "dana", "asset": "eur", "template": "bollinger", "title": "Euro Band Trader", "price_cents": 900,
     "pitch": "Trades the euro against the dollar when price stretches outside its Bollinger bands."},
)

FAST_DEMO = {"seller": "priya", "asset": "btc", "template": "trend", "title": "Fast Demo Agent (1s, 2-minute hold)",
             "price_cents": 900, "symbol": "binance:BTCUSDT", "interval": "1s", "mode": "hold", "trial_s": 120,
             "pitch": "A one-second Bitcoin agent with a 120-second hold, so you can watch the whole hold, verdict "
                      "and capture-or-void cycle in two minutes."}

BARS_WANTED = 1000
MIN_TRIAL_S = 1800
MAX_TRIAL_S = 259_200


def seed_sellers() -> dict[str, dict]:
    payout = get_settings().demo_payout_email.strip()
    return {seller["key"]: upsert_seller("SEED-" + seller["key"].upper(), seller["name"], payout or seller["email"],
                                         True)
            for seller in SELLERS}


def hold_trial_s(interval: str) -> int:
    return min(MAX_TRIAL_S, max(MIN_TRIAL_S, 10 * INTERVAL_SECONDS[interval]))


def fetch(symbol: str, interval: str) -> list | None:
    try:
        bars = markets.closed_candles(symbol, interval, BARS_WANTED)
    except Exception as err:
        log.info("seed could not fetch %s %s: %s", symbol, interval, type(err).__name__)
        return None
    return bars if len(bars) >= MIN_BARS else None


def markets_online() -> bool:
    return not get_settings().markets_offline and fetch("binance:BTCUSDT", "1h") is not None


def choose_data(spec: dict, online: bool) -> tuple[str, str, list] | None:
    asset = ASSETS[spec["asset"]]
    options = []
    if online and asset["live"]:
        options.append(asset["live"])
    options.append(asset["sample"])
    for symbol, interval in options:
        bars = fetch(symbol, interval)
        if bars:
            return symbol, interval, bars
    return None


def seed_listing(owner: dict, spec: dict, symbol: str, interval: str, bars: list, mode: str, trial_s: int) -> dict:
    strategy = template_spec(spec["template"], symbol, interval).model_copy(
        update={"name": spec["title"][:60]})
    agent = agents.create_agent(owner["id"], spec["title"][:60], symbol, interval)
    version = agents.save_version(owner["id"], agent["id"], strategy, built_by=f"template:{spec['template']}")
    result = run_backtest(strategy, bars, symbol=symbol, interval=interval, quote=markets.quote_currency(symbol),
                          source_kind=markets.source_kind(symbol))
    proof = proofs.store_proof("backtest", version["id"], strategy, result, bars=bars)
    return create_listing(owner["id"], NewListing(
        version_id=version["id"], title=spec["title"], pitch=spec["pitch"], price_cents=spec["price_cents"],
        mode=mode, trial_s=trial_s, min_return_bps=0, max_loss_bps=1000, proof_id=proof["id"],
        allow_test_drive=True))


def seed_regular(sellers: dict, online: bool) -> int:
    created = 0
    for number, spec in enumerate(AGENTS):
        if one("SELECT id FROM listings WHERE title = ?", (spec["title"],)):
            continue
        chosen = choose_data(spec, online)
        if chosen is None:
            continue
        symbol, interval, bars = chosen
        live = not symbol.startswith("sample:")
        mode = "hold" if live and number % 2 == 0 else "instant"
        seed_listing(sellers[spec["seller"]], spec, symbol, interval, bars, mode, hold_trial_s(interval))
        created += 1
    return created


def seed_fast_demo(sellers: dict) -> int:
    spec = FAST_DEMO
    if one("SELECT id FROM listings WHERE title = ?", (spec["title"],)):
        return 0
    bars = fetch(spec["symbol"], spec["interval"])
    if bars is None:
        return 0
    seed_listing(sellers[spec["seller"]], spec, spec["symbol"], spec["interval"], bars, spec["mode"], spec["trial_s"])
    return 1


def seed_demo() -> int:
    if paypal_mode() == "live":
        log.warning("demo seeding is skipped because PayPal is live")
        return 0
    sellers = seed_sellers()
    online = markets_online()
    created = seed_regular(sellers, online)
    if online:
        created += seed_fast_demo(sellers)
    return created
