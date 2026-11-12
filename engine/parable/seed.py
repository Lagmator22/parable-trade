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
from parable.seed_tune import best_candidate

log = logging.getLogger("parable.seed")

SELLERS = (
    {"key": "priya", "name": "Priya Raman", "email": "priya.raman@example.com"},
    {"key": "tomas", "name": "Tomas Lindqvist", "email": "tomas.lindqvist@example.com"},
    {"key": "dana", "name": "Dana Whitfield", "email": "dana.whitfield@example.com"},
)

ASSETS = {
    "btc": {"live": "binance:BTCUSDT", "sample": ("sample:BTCUSDT", "1h")},
    "eth": {"live": "binance:ETHUSDT", "sample": ("sample:ETHUSDT", "1d")},
    "gold": {"live": "binance:PAXGUSDT", "sample": ("sample:PAXGUSDT", "1d")},
    "sol": {"live": "binance:SOLUSDT", "sample": ("sample:SOLUSDT", "1h")},
    "eur": {"live": "fx:EURUSD", "sample": ("sample:EURUSD", "1d")},
}

AGENTS = (
    {"seller": "priya", "asset": "btc", "templates": ("trend",), "intervals": ("1d", "4h"),
     "title": "Bitcoin Trend Rider", "price_cents": 2900,
     "pitch": "Follows the Bitcoin trend with a stop loss. Every number is reproducible from its proof."},
    {"seller": "priya", "asset": "eth", "templates": ("rsi",), "intervals": ("1d", "4h"),
     "title": "Ether RSI Swing", "price_cents": 1900,
     "pitch": "Buys oversold Ether and sells when momentum recovers."},
    {"seller": "tomas", "asset": "gold", "templates": ("mean_revert",), "intervals": ("1h", "4h"),
     "title": "Gold Mean Reverter", "price_cents": 3900,
     "pitch": "Fades stretched moves in tokenised gold and waits for the average to pull back."},
    {"seller": "tomas", "asset": "sol", "templates": ("breakout",), "intervals": ("1d", "4h"),
     "title": "Solana Breakout", "price_cents": 1400,
     "pitch": "Enters when Solana breaks its recent high and rides it with a trailing exit."},
    {"seller": "dana", "asset": "btc", "templates": ("macd",), "intervals": ("1d",),
     "title": "Bitcoin MACD Pulse", "price_cents": 4900,
     "pitch": "Trades Bitcoin MACD momentum crossovers with fixed risk."},
    {"seller": "dana", "asset": "eur", "templates": ("rsi", "macd"), "intervals": ("1d",),
     "title": "Euro Momentum Trader", "price_cents": 900,
     "pitch": "Trades the euro against the dollar on momentum swings and keeps a stop loss on every trade."},
    {"seller": "dana", "asset": "btc", "templates": ("mean_revert",), "intervals": ("4h", "1h"),
     "title": "Bitcoin Range Trader", "price_cents": 2400,
     "pitch": "Buys Bitcoin when it stretches below its average and sells when it snaps back."},
)

TUNED_NOTE = " Its parameters were tuned on past data, so live results can differ from the backtest."

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


def candidate_list(spec: dict, online: bool) -> list[tuple[str, str, str, list]]:
    asset = ASSETS[spec["asset"]]
    options = [(asset["live"], interval) for interval in spec["intervals"]] if online else []
    found = []
    for symbol, interval in options:
        bars = fetch(symbol, interval)
        if bars:
            found += [(template, symbol, interval, bars) for template in spec["templates"]]
    if found:
        return found
    symbol, interval = asset["sample"]
    bars = fetch(symbol, interval)
    return [(template, symbol, interval, bars) for template in spec["templates"]] if bars else []


def seed_listing(owner: dict, spec: dict, chosen: dict, mode: str, trial_s: int) -> dict:
    symbol, interval, bars, strategy = chosen["symbol"], chosen["interval"], chosen["bars"], chosen["strategy"]
    agent = agents.create_agent(owner["id"], spec["title"][:60], symbol, interval)
    version = agents.save_version(owner["id"], agent["id"], strategy, built_by=f"template:{chosen['template']}")
    result = run_backtest(strategy, bars, symbol=symbol, interval=interval, quote=markets.quote_currency(symbol),
                          source_kind=markets.source_kind(symbol))
    proof = proofs.store_proof("backtest", version["id"], strategy, result, bars=bars)
    pitch = spec["pitch"] + (TUNED_NOTE if chosen["tuned"] else "")
    return create_listing(owner["id"], NewListing(
        version_id=version["id"], title=spec["title"], pitch=pitch, price_cents=spec["price_cents"],
        mode=mode, trial_s=trial_s, min_return_bps=0, max_loss_bps=1000, proof_id=proof["id"],
        allow_test_drive=True))


def hold_allowed(symbol: str, interval: str) -> bool:
    return not symbol.startswith("sample:") and 10 * INTERVAL_SECONDS[interval] <= MAX_TRIAL_S


def seed_regular(sellers: dict, online: bool) -> int:
    created = 0
    for spec in AGENTS:
        if one("SELECT id FROM listings WHERE title = ?", (spec["title"],)):
            continue
        chosen = best_candidate(candidate_list(spec, online), spec["title"])
        if chosen is None:
            continue
        hold = hold_allowed(chosen["symbol"], chosen["interval"])
        mode = "hold" if hold else "instant"
        seed_listing(sellers[spec["seller"]], spec, chosen, mode, hold_trial_s(chosen["interval"]))
        created += 1
    return created


def seed_fast_demo(sellers: dict) -> int:
    spec = FAST_DEMO
    if one("SELECT id FROM listings WHERE title = ?", (spec["title"],)):
        return 0
    bars = fetch(spec["symbol"], spec["interval"])
    if bars is None:
        return 0
    strategy = template_spec(spec["template"], spec["symbol"], spec["interval"]).model_copy(
        update={"name": spec["title"][:60]})
    chosen = {"symbol": spec["symbol"], "interval": spec["interval"], "bars": bars, "strategy": strategy,
              "template": spec["template"], "tuned": False}
    seed_listing(sellers[spec["seller"]], spec, chosen, spec["mode"], spec["trial_s"])
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
