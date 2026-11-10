import json

from parable import analyst
from parable.listings import list_listings

MAX_QUERY = 400
MAX_REASON = 400
MAX_ALTERNATIVES = 2
CAUTIOUS_WORDS = ("low-risk", "low risk", "safe", "safer", "careful", "conservative", "cautious")
NO_MATCH_REASON = "No active bot fits that budget yet."


def survival_label(record: dict) -> str:
    if not record["ended"]:
        return "no finished runs yet"
    return f"{record['survived']} of {record['ended']} runs survived"


def affordable(listings: list[dict], budget_cents: int | None) -> list[dict]:
    if budget_cents is None:
        return listings
    return [listing for listing in listings if listing["price_cents"] <= budget_cents]


def score(listing: dict, cautious: bool) -> float:
    record = listing["seller_record"]
    base = record["survival_rate"] * 100 + min(record["ended"], 5) * 2 + record["avg_return_bps"] / 100
    base -= 0 if record["ended"] else 40
    return base - listing["rules"]["max_loss_bps"] / 20 if cautious else base


def wants_caution(query: str) -> bool:
    lowered = query.lower()
    return any(word in lowered for word in CAUTIOUS_WORDS)


def ranked(listings: list[dict], query: str) -> list[dict]:
    cautious = wants_caution(query)
    return sorted(listings, key=lambda listing: (-score(listing, cautious), listing["price_cents"], listing["id"]))


def fallback_reason(listing: dict) -> str:
    record = listing["seller_record"]
    return (f"{listing['title']} has the strongest record within your limits: {survival_label(record)}, "
            f"priced at ${listing['price_cents'] / 100:.2f}, and you pay only if it passes its probation.")


def fallback(candidates: list[dict], query: str) -> dict:
    if not candidates:
        return {"listing_id": None, "reason": NO_MATCH_REASON, "alternatives": [], "by": "rules"}
    order = ranked(candidates, query)
    return {"listing_id": order[0]["id"], "reason": fallback_reason(order[0]),
            "alternatives": [listing["id"] for listing in order[1:1 + MAX_ALTERNATIVES]], "by": "rules"}


def compact(listing: dict) -> dict:
    record = listing["seller_record"]
    return {
        "id": listing["id"],
        "title": listing["title"],
        "pitch": listing["pitch"][:200],
        "strategy": listing["rules"]["strategy"],
        "price_dollars": listing["price_cents"] / 100,
        "probation_minutes": listing["probation_s"] // 60,
        "loss_limit_percent": listing["rules"]["max_loss_bps"] / 100,
        "promised_min_return_percent": listing["min_return_bps"] / 100,
        "finished_runs": record["ended"],
        "survived_runs": record["survived"],
        "average_return_percent": record["avg_return_bps"] / 100,
        "worst_return_percent": record["worst_return_bps"] / 100,
        "probations_passed": record["probation_passed"],
        "probations_failed": record["probation_failed"],
    }


def build_prompt(query: str, candidates: list[dict]) -> str:
    return (
        "You are a careful shopping agent for a marketplace of AI trading bots. The buyer pays only if a bot "
        "survives its probation. Pick the single best bot for the buyer's request using only the listings given "
        "and their numbers; never invent numbers or ids. Prefer proven records over promises.\n"
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
