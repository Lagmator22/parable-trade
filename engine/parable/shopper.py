import json

from parable import analyst
from parable.listing_views import list_listings

MAX_QUERY = 400
MAX_REASON = 400
MAX_ALTERNATIVES = 2
CAUTIOUS_WORDS = ("low-risk", "low risk", "safe", "safer", "careful", "conservative", "cautious")
NO_MATCH_REASON = "No active agent fits that budget yet."


def affordable(listings: list[dict], budget_cents: int | None) -> list[dict]:
    if budget_cents is None:
        return listings
    return [listing for listing in listings if listing["price_cents"] <= budget_cents]


def excess_return(listing: dict) -> float:
    head = listing["headline"]
    return (head.get("total_return_pct") or 0) - (head.get("benchmark_return_pct") or 0)


def score(listing: dict, cautious: bool) -> float:
    drawdown = listing["headline"].get("max_drawdown_pct") or 0
    reruns = listing["reruns"]
    base = excess_return(listing) + 2 * reruns["matched"] - 5 * (reruns["count"] - reruns["matched"])
    return base - drawdown * (1.0 if cautious else 0.25)


def wants_caution(query: str) -> bool:
    lowered = query.lower()
    return any(word in lowered for word in CAUTIOUS_WORDS)


def ranked(listings: list[dict], query: str) -> list[dict]:
    cautious = wants_caution(query)
    return sorted(listings, key=lambda listing: (-score(listing, cautious), listing["price_cents"], listing["id"]))


def fallback_reason(listing: dict) -> str:
    head = listing["headline"]
    return (f"{listing['title']} returned {head.get('total_return_pct', 0):+.1f}% in its proof against "
            f"{head.get('benchmark_return_pct', 0):+.1f}% for buy and hold, with a worst drawdown of "
            f"{head.get('max_drawdown_pct', 0):.1f}%, priced at ${listing['price_cents'] / 100:.2f}.")


def fallback(candidates: list[dict], query: str) -> dict:
    if not candidates:
        return {"listing_id": None, "reason": NO_MATCH_REASON, "alternatives": [], "by": "rules"}
    order = ranked(candidates, query)
    return {"listing_id": order[0]["id"], "reason": fallback_reason(order[0]),
            "alternatives": [listing["id"] for listing in order[1:1 + MAX_ALTERNATIVES]], "by": "rules"}


def compact(listing: dict) -> dict:
    head, track = listing["headline"], listing["track"]
    return {
        "id": listing["id"],
        "title": listing["title"],
        "asset": listing["symbol"],
        "kind": listing["kind"],
        "data_badge": {"market": "market data", "sample": "sample data", "creator": "creator data"}.get(
            listing["data"]["source_kind"], "market data") if listing["data"] else "market data",
        "mode": listing["mode"],
        "price_dollars": listing["price_cents"] / 100,
        "proof_return_percent": head.get("total_return_pct"),
        "buy_and_hold_percent": head.get("benchmark_return_pct"),
        "max_drawdown_percent": head.get("max_drawdown_pct"),
        "trades": head.get("trades"),
        "reruns_matched": listing["reruns"]["matched"],
        "reruns_total": listing["reruns"]["count"],
        "live_track_percent": track["equity_pct"] if track else None,
        "live_track_seconds": track["seconds"] if track else None,
    }


def build_prompt(query: str, candidates: list[dict]) -> str:
    return (
        "You are a careful shopping agent for a marketplace of trading agents. Each agent shows a reproducible "
        "backtest proof and a live track record. Pick the single best agent for the buyer's request using only the "
        "listings given and their numbers; never invent numbers or ids. Prefer proven records over promises.\n"
        f"Buyer request: {json.dumps(query)}\n"
        f"Listings: {json.dumps([compact(listing) for listing in candidates])}\n"
        'Reply with JSON only: {"listing_id": "<one id from the listings>", "reason": "<one or two sentences>", '
        '"alternatives": ["<up to 2 other ids>"]}'
    )


def accept_answer(answer: dict | None, candidates: list[dict]) -> dict | None:
    if not answer:
        return None
    known = {listing["id"] for listing in candidates}
    chosen, reason = answer.get("listing_id"), answer.get("reason")
    alternatives = answer.get("alternatives", [])
    if chosen not in known or not isinstance(reason, str) or not 0 < len(reason.strip()) <= MAX_REASON:
        return None
    if not isinstance(alternatives, list) or not all(isinstance(item, str) for item in alternatives):
        return None
    valid = [item for item in dict.fromkeys(alternatives) if item in known and item != chosen]
    return {"listing_id": chosen, "reason": " ".join(reason.split()), "alternatives": valid[:MAX_ALTERNATIVES]}


def recommend(query: str, budget_cents: int | None = None) -> dict:
    query = (query or "").strip()[:MAX_QUERY]
    candidates = affordable(list_listings(), budget_cents)
    if not candidates:
        return fallback(candidates, query)
    accepted = accept_answer(analyst.ask(build_prompt(query, candidates)), candidates)
    if accepted is None:
        return fallback(candidates, query)
    return {**accepted, "by": analyst.brain_name()}
