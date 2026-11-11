import json

from parable.db import one, rows
from parable.purchase_views import is_entitled

HIDDEN_PURCHASES = ("created", "cancelled")


def agent_summary(agent: dict) -> dict:
    listing = one("SELECT l.id FROM listings l JOIN agent_versions v ON v.id = l.version_id"
                  " WHERE v.agent_id = ? AND l.active = 1 ORDER BY l.created_at DESC LIMIT 1", (agent["id"],))
    proof = one("SELECT metrics_json FROM proofs WHERE version_id = ? AND kind = 'backtest'"
                " ORDER BY created_at DESC, id DESC LIMIT 1", (agent["latest_version_id"],)) \
        if agent["latest_version_id"] else None
    return {"id": agent["id"], "name": agent["name"], "symbol": agent["symbol"], "interval": agent["interval"],
            "status": agent["status"], "latest_version_id": agent["latest_version_id"],
            "listing_id": listing["id"] if listing else None, "updated_at": agent["updated_at"],
            "headline": json.loads(proof["metrics_json"]) if proof else None}


def bought_agent(purchase: dict) -> dict:
    listing = one("SELECT l.id, l.title, l.symbol, l.interval, v.spec_hash FROM listings l"
                  " JOIN agent_versions v ON v.id = l.version_id WHERE l.id = ?", (purchase["listing_id"],)) or {}
    return {"purchase_id": purchase["id"], "listing_id": purchase["listing_id"], "title": listing.get("title", ""),
            "mode": purchase["mode"], "status": purchase["status"], "spec_hash": listing.get("spec_hash", ""),
            "symbol": listing.get("symbol", ""), "interval": listing.get("interval", ""),
            "entitled": is_entitled(purchase)}


def my_agents(account_id: str) -> dict:
    built = rows("SELECT * FROM agents WHERE owner_id = ? ORDER BY updated_at DESC, id", (account_id,))
    bought = rows("SELECT * FROM purchases WHERE buyer_id = ? ORDER BY created_at DESC, id", (account_id,))
    return {"built": [agent_summary(agent) for agent in built],
            "bought": [bought_agent(purchase) for purchase in bought if purchase["status"] not in HIDDEN_PURCHASES]}


def my_purchases(account_id: str) -> list[dict]:
    found = rows("SELECT p.id, p.status, p.mode, p.listing_id, p.amount_cents, p.created_at, l.title FROM purchases p"
                 " LEFT JOIN listings l ON l.id = p.listing_id WHERE p.buyer_id = ?"
                 " ORDER BY p.created_at DESC, p.id", (account_id,))
    return [{"id": p["id"], "status": p["status"], "mode": p["mode"], "listing_id": p["listing_id"],
             "title": p["title"] or "", "amount_cents": p["amount_cents"], "created_at": p["created_at"]}
            for p in found]


def my_sales(account_id: str) -> list[dict]:
    out = []
    for listing in rows("SELECT id, title, mode FROM listings WHERE seller_id = ? ORDER BY created_at DESC, id",
                        (account_id,)):
        sold = rows("SELECT status, amount_cents, fee_cents FROM purchases WHERE listing_id = ?", (listing["id"],))
        live = [p for p in sold if p["status"] not in HIDDEN_PURCHASES]
        out.append({"listing_id": listing["id"], "title": listing["title"], "mode": listing["mode"],
                    "purchases": len(live),
                    "captured_cents": sum(p["amount_cents"] for p in sold if p["status"] in ("captured", "paid_out")),
                    "paid_out_cents": sum(p["amount_cents"] - p["fee_cents"] for p in sold
                                          if p["status"] == "paid_out")})
    return out
