import os

import httpx
from mcp.server.fastmcp import FastMCP

DEFAULT_URL = "http://localhost:8000"
REQUEST_TIMEOUT_S = 60.0
BUY_INSTRUCTION = (
    "A human must open this link, sign in and pay with PayPal. Agents cannot buy on their own. In hold mode the "
    "payment is only held until the agent passes its trial."
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
    head, track = listing["headline"], listing["track"]
    return {
        "listing_id": listing["id"],
        "title": listing["title"],
        "seller": listing["seller"]["name"],
        "asset": listing["symbol"],
        "kind": listing["kind"],
        "interval": listing["interval"],
        "mode": listing["mode"],
        "price_dollars": listing["price_cents"] / 100,
        "proof_return_percent": head["total_return_pct"],
        "buy_and_hold_percent": head["benchmark_return_pct"],
        "max_drawdown_percent": head["max_drawdown_pct"],
        "trades": head["trades"],
        "data": listing["data"]["source_kind"] if listing["data"] else None,
        "reruns_matched": listing["reruns"]["matched"],
        "reruns_total": listing["reruns"]["count"],
        "live_track_percent": track["equity_pct"] if track else None,
        "free_test_drive": listing["allow_test_drive"],
    }


@mcp.tool()
def find_agents(query: str, kind: str | None = None, max_price_dollars: float | None = None) -> dict:
    budget = None if max_price_dollars is None else int(round(max_price_dollars * 100))
    shortlist = call("POST", "/api/shopper", json={"query": query, "budget_cents": budget})
    if "error" in shortlist:
        return shortlist
    params = {"kind": kind} if kind else {}
    listings = call("GET", "/api/listings", params=params)
    if isinstance(listings, dict):
        return listings
    candidates = [brief(item) for item in listings if budget is None or item["price_cents"] <= budget]
    return {"recommended_listing_id": shortlist["listing_id"], "reason": shortlist["reason"],
            "alternatives": shortlist["alternatives"], "by": shortlist["by"], "candidates": candidates}


@mcp.tool()
def due_diligence(listing_id: str) -> dict:
    return call("GET", f"/api/listings/{listing_id}/diligence")


@mcp.tool()
def proof(listing_id: str) -> dict:
    detail = call("GET", f"/api/listings/{listing_id}")
    if "error" in detail:
        return detail
    claim = detail["proof"]
    return {"listing_id": listing_id, "data": claim["data"], "metrics": claim["metrics"],
            "trades": claim["trades_count"], "engine_version": claim["engine_version"],
            "result_hash": claim["result_hash"], "ledger_seq": claim["ledger_seq"]}


@mcp.tool()
def rerun_proof(listing_id: str) -> dict:
    result = call("POST", f"/api/listings/{listing_id}/rerun", json={})
    if "error" in result:
        return result
    return {"listing_id": listing_id, "match": result["match"], "claimed_hash": result["claim"]["result_hash"],
            "rerun_hash": result["rerun"]["result_hash"], "diff": result["diff"]}


@mcp.tool()
def test_drive(listing_id: str, symbol: str | None = None) -> dict:
    body = {"symbol": symbol} if symbol else {}
    result = call("POST", f"/api/listings/{listing_id}/test-drive", json=body)
    if "error" in result:
        return result
    return {"listing_id": listing_id, "data": result["proof"]["data"], "metrics": result["proof"]["metrics"],
            "claim_metrics": result["claim"]["metrics"] if result["claim"] else None}


@mcp.tool()
def buy_link(listing_id: str) -> dict:
    listing = call("GET", f"/api/listings/{listing_id}")
    if "error" in listing:
        return listing
    base = os.environ.get("PARABLE_PUBLIC_URL") or os.environ.get("PARABLE_URL", DEFAULT_URL)
    return {"url": f"{base.rstrip('/')}/#agent/{listing_id}", "instruction": BUY_INSTRUCTION}


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
