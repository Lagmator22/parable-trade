
from market_support import make_listing, make_seller
from parable import ledger, market
from parable.db import one


def private_run(manager, listing):
    return manager.start_for_version(listing["seller_id"], listing["version_id"], "fake:BTCUSDT", "1h", "practice",
                                     "Secret draft")


def test_public_ledger_hides_private_runs(client, manager):
    listing = make_listing()
    practice = private_run(manager, listing)
    ledger.append("run.trade", f"run:{practice['id']}", {"side": "buy"})
    subjects = {e["subject"] for e in client.get("/api/ledger?limit=500").json()}
    assert f"run:{practice['id']}" not in subjects
    assert f"run:{listing['track_run_id']}" in subjects
    assert client.get(f"/api/ledger?subject=run:{practice['id']}").json() == []


def test_owner_sees_own_private_run_entries_unredacted(client, manager):
    client.post("/paypal/mock-login", data={"name": "Ada Seller", "email": "ada@example.com"})
    owner = one("SELECT * FROM sellers WHERE email = ?", ("ada@example.com",))
    listing = make_listing(owner)
    practice = private_run(manager, listing)
    found = client.get(f"/api/ledger?subject=run:{practice['id']}").json()
    assert found and found[-1]["data"]["name"] == "Secret draft" and "redacted" not in found[-1]


def test_probation_ledger_entries_hide_account_details(client, manager):
    listing = make_listing()
    buyer = make_seller("Bo", "bo@example.com")
    pid = market.start_purchase(listing["id"], buyer["id"])["purchase_id"]
    run = manager.start_for_version(buyer["id"], listing["version_id"], "fake:BTCUSDT", "1h", "probation", "My copy",
                                    listing_id=listing["id"], purchase_id=pid)
    entries = client.get(f"/api/ledger?subject=run:{run['id']}").json()
    assert entries and all(e["redacted"] for e in entries)
    for entry in entries:
        assert entry["data"].get("seller_id") is None and "purchase_id" not in entry["data"]
        assert "name" not in entry["data"] and "rules" not in entry["data"]


def test_purchase_entries_hide_identity_and_paypal_ids(client, manager):
    listing = make_listing()
    buyer = make_seller("Bo", "bo@example.com")
    pid = market.start_purchase(listing["id"], buyer["id"])["purchase_id"]
    ledger.append("payment.captured", f"purchase:{pid}", {"capture_id": "CAP-1", "amount_cents": 2000, "mode": "hold"})
    ledger.append("payout.sent", f"purchase:{pid}", {"payout_batch_id": "PB-1", "amount_cents": 1800})
    text = client.get("/api/ledger?limit=500").json()
    blob = str(text)
    assert pid not in blob and "CAP-1" not in blob and "PB-1" not in blob
    created = [e for e in text if e["kind"] == "purchase.created"][0]
    assert created["data"]["listing_id"] == listing["id"] and created["data"]["amount_cents"] == 2000
    assert created["redacted"] is True and created["hash"]


def test_redaction_is_view_only_and_chain_still_verifies(client, manager):
    listing = make_listing()
    private_run(manager, listing)
    market.start_purchase(listing["id"], make_seller("Bo", "bo@example.com")["id"])
    client.get("/api/ledger?limit=500")
    assert client.get("/api/ledger/verify").json()["ok"] is True
    assert ledger.verify()["ok"] is True


def test_run_endpoint_redacts_entries_for_strangers(client, manager):
    listing = make_listing()
    buyer = make_seller("Bo", "bo@example.com")
    pid = market.start_purchase(listing["id"], buyer["id"])["purchase_id"]
    run = manager.start_for_version(buyer["id"], listing["version_id"], "fake:BTCUSDT", "1h", "probation", "My copy",
                                    listing_id=listing["id"], purchase_id=pid)
    body = client.get(f"/api/runs/{run['id']}").json()
    assert body["entries"] and body["seller_id"] is None
    for entry in body["entries"]:
        assert entry["data"].get("seller_id") is None and "purchase_id" not in entry["data"]
        assert "name" not in entry["data"] and "rules" not in entry["data"]
    track = client.get(f"/api/runs/{listing['track_run_id']}").json()
    assert track["entries"] and "redacted" not in track["entries"][-1]
