import os

import httpx
from mcp.server.fastmcp import FastMCP

DEFAULT_URL = "http://localhost:8000"
REQUEST_TIMEOUT_S = 60.0
BUY_INSTRUCTION = (
    "A human must open approve_url and approve the payment in PayPal. The money is only held, never charged, "
    "until the bot survives its probation. Keep buyer_token private and use it with purchase_status."
)

mcp = FastMCP("Parable")


def get_client() -> httpx.Client:
    return httpx.Client(base_url=os.environ.get("PARABLE_URL", DEFAULT_URL), timeout=REQUEST_TIMEOUT_S)


def call(method: str, path: str, **options) -> dict | list:
    try:
        with get_client() as client:
            response = client.request(method, path, **options)
    except httpx.HTTPError as err:
        return {"error": f"could not reach Parable: {type(err).__name__}"}
    payload = response.json() if response.content else {}
    if response.is_error:
        detail = payload.get("detail", "request failed") if isinstance(payload, dict) else "request failed"
        return {"error": str(detail), "status": response.status_code}
    return payload


def brief(listing: dict) -> dict:
    record = listing["seller_record"]
    return {
        "listing_id": listing["id"],
        "title": listing["title"],
        "seller": listing["seller"]["name"],
        "price_dollars": listing["price_cents"] / 100,
        "probation_minutes": listing["probation_s"] // 60,
        "promised_min_return_percent": listing["min_return_bps"] / 100,
        "loss_limit_percent": listing["rules"]["max_loss_bps"] / 100,
        "strategy": listing["rules"]["strategy"],
        "finished_runs": record["ended"],
        "survived_runs": record["survived"],
        "probations_passed": record["probation_passed"],
        "probations_failed": record["probation_failed"],
    }


@mcp.tool()
def find_bots(query: str, max_price_dollars: float | None = None) -> dict:
    budget = None if max_price_dollars is None else int(round(max_price_dollars * 100))
    shortlist = call("POST", "/api/shopper", json={"query": query, "budget_cents": budget})
    if "error" in shortlist:
        return shortlist
    listings = call("GET", "/api/listings")
    if isinstance(listings, dict):
        return listings
    candidates = [brief(item) for item in listings if budget is None or item["price_cents"] <= budget]
    return {"recommended_listing_id": shortlist["listing_id"], "reason": shortlist["reason"],
            "alternatives": shortlist["alternatives"], "by": shortlist["by"], "candidates": candidates}


@mcp.tool()
def due_diligence(listing_id: str) -> dict:
    return call("GET", f"/api/listings/{listing_id}/diligence")


@mcp.tool()
def buy_bot(listing_id: str) -> dict:
    created = call("POST", "/api/purchases", json={"listing_id": listing_id, "via": "agent"})
    if "error" in created:
        return created
    return {**created, "instruction": BUY_INSTRUCTION}


@mcp.tool()
def purchase_status(purchase_id: str, buyer_token: str) -> dict:
    return call("GET", f"/api/purchases/{purchase_id}", headers={"x-buyer-token": buyer_token})


@mcp.tool()
def seller_record(seller_id: str) -> dict:
    return call("GET", f"/api/sellers/{seller_id}")


@mcp.tool()
def verify_ledger() -> dict:
    return call("GET", "/api/ledger/verify")


@mcp.tool()
def market_stats() -> dict:
    return call("GET", "/api/stats")


if __name__ == "__main__":
    mcp.run()
