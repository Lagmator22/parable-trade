import json

import pytest

from agents_support import SYMBOL, INTERVAL, add_listing, clean_lab, make_account, new_agent, new_version
from lab_support import fake_market, make_bars
from parable import db, ledger, proofs
from parable.errors import LabError
from parable.lab import markets
from parable.lab.backtest import data_hash, run_backtest
from parable.lab.spec import load_spec


def headline(owner, fake_market, bars=None):
    agent = new_agent(owner)
    version = new_version(owner, agent)
    spec = load_spec(version["id"])
    bars = bars or fake_market.bars_by_code["BTCUSDT"]
    result = run_backtest(spec, bars, symbol=SYMBOL, interval=INTERVAL, quote="USDT", source_kind="market")
    row = proofs.store_proof("backtest", version["id"], spec, result, bars=bars)
    listing = add_listing(owner, version["id"], row["id"])
    return version, spec, row, listing


def test_store_proof_writes_row_bars_and_ledger(fake_market):
    owner = make_account()
    version, spec, row, _ = headline(owner, fake_market)
    assert row["id"].startswith("pf_") and row["kind"] == "backtest" and row["ledger_seq"]
    entry = ledger.entries(subject=f"proof:{row['id']}")[0]
    assert entry["kind"] == "proof.stored" and entry["data"]["result_hash"] == row["result_hash"]
    assert spec.entry not in json.dumps(entry)
    assert proofs.load_bars(row["data_hash"]) == fake_market.bars_by_code["BTCUSDT"]
    assert row["trades_count"] == len(json.loads(row["trades_json"]))
    with pytest.raises(ValueError):
        proofs.store_proof("nonsense", version["id"], spec, {})


def test_proof_view_public_is_an_allow_list(fake_market):
    owner = make_account()
    version, spec, row, _ = headline(owner, fake_market)
    public = proofs.proof_view(row, owner=False)
    assert set(public) == {"id", "kind", "spec_hash", "symbol", "interval", "data", "metrics", "curve", "trades_count",
                           "engine_version", "result_hash", "ledger_seq", "matched", "by", "created_at", "assumptions",
                           "verifiable"}
    text = json.dumps(public)
    assert spec.entry not in text and spec.exit not in text and "trades" not in public.keys() - {"trades_count"}
    private = proofs.proof_view(row, owner=True)
    assert {"trades", "markers", "version_id"} <= set(private) and private["by"] == "seller"
    assert public["data"]["data_hash"] == data_hash(fake_market.bars_by_code["BTCUSDT"])


def test_get_proof_visibility(fake_market):
    ada, bob = make_account("Ada"), make_account("Bob")
    version, _, row, listing = headline(ada, fake_market)
    assert "trades" in proofs.get_proof(row["id"], ada["id"])
    public = proofs.get_proof(row["id"], bob["id"])
    assert "trades" not in public and public["id"] == row["id"]
    db.execute("UPDATE listings SET active = 0")
    with pytest.raises(LabError) as err:
        proofs.get_proof(row["id"], bob["id"])
    assert err.value.status == 404
    with pytest.raises(LabError):
        proofs.get_proof(row["id"], None)
    with pytest.raises(LabError):
        proofs.get_proof("pf_missing", ada["id"])


def test_rerun_matches_and_records(fake_market):
    ada = make_account("Ada")
    _, _, row, listing = headline(ada, fake_market)
    out = proofs.rerun_listing(listing, "v_visitor0000000a")
    assert out["match"] is True and out["refetched"] is False and out["data_hash_match"] is None
    assert out["rerun"]["matched"] is True and out["rerun"]["by"] == "visitor"
    assert out["claim"]["id"] == row["id"] and set(out["diff"]) >= {"total_return_pct"}
    assert all(v["claim"] == v["rerun"] for v in out["diff"].values())
    assert "trades" not in out["rerun"]
    checks = proofs.listing_checks(listing)
    assert [c["kind"] for c in checks] == ["rerun"]
    seller_run = proofs.rerun_listing(listing, ada["id"])
    assert seller_run["rerun"]["by"] == "seller"


def test_rerun_without_network_uses_stored_bars(fake_market):
    ada = make_account("Ada")
    _, _, _, listing = headline(ada, fake_market)
    fake_market.fail = True
    assert proofs.rerun_listing(listing, "v_visitor0000000a")["match"] is True
    assert fake_market.calls["candles"] == 0


def test_rerun_refetch_detects_changed_data(fake_market):
    ada = make_account("Ada")
    bars = fake_market.bars_by_code["BTCUSDT"]
    _, _, _, listing = headline(ada, fake_market)
    same = proofs.rerun_listing(listing, "v_visitor0000000a", refetch=True)
    assert same["refetched"] is True and same["data_hash_match"] is True and same["match"] is True
    fake_market.bars_by_code["BTCUSDT"] = [b[:4] + [b[4] * 1.01] + b[5:] if i % 7 == 0 else b for i, b in enumerate(bars)]
    markets.clear_cache()
    moved = proofs.rerun_listing(listing, "v_visitor0000000a", refetch=True)
    assert moved["data_hash_match"] is False and moved["match"] is False and moved["rerun"]["matched"] is False


def test_rerun_detects_tampered_claim(fake_market):
    ada = make_account("Ada")
    _, _, row, listing = headline(ada, fake_market)
    db.execute("UPDATE proofs SET result_hash = 'bad' WHERE id = ?", (row["id"],))
    assert proofs.rerun_listing(listing, "v_visitor0000000a")["match"] is False


def test_rerun_errors(fake_market):
    ada = make_account("Ada")
    with pytest.raises(LabError) as err:
        proofs.rerun_listing("l_missing", "v_x")
    assert err.value.status == 404
    version = new_version(ada, new_agent(ada))
    bare = add_listing(ada, version["id"])
    with pytest.raises(LabError) as err:
        proofs.rerun_listing(bare, "v_x")
    assert err.value.status == 404
    _, _, row, listing = headline(ada, fake_market)
    db.execute("DELETE FROM bar_sets")
    with pytest.raises(LabError):
        proofs.rerun_listing(listing, "v_x")


def test_test_drive_other_symbol_and_flags(fake_market):
    ada = make_account("Ada")
    fake_market.bars_by_code["ETHUSDT"] = make_bars(400, seed=9)
    _, _, row, listing = headline(ada, fake_market)
    out = proofs.test_drive(listing, "v_visitor0000000a", symbol="fake:ETHUSDT")
    assert out["proof"]["kind"] == "testdrive" and out["proof"]["symbol"] == "fake:ETHUSDT"
    assert out["claim"]["id"] == row["id"] and "trades" not in out["proof"]
    default = proofs.test_drive(listing, "v_visitor0000000a")
    assert default["proof"]["symbol"] == SYMBOL
    assert {c["kind"] for c in proofs.listing_checks(listing)} == {"testdrive"}
    with pytest.raises(LabError) as err:
        proofs.test_drive(listing, "v_x", symbol="upload:d_abc1234567")
    assert err.value.status == 403
    with pytest.raises(LabError) as err:
        proofs.test_drive(listing, "v_x", interval="9z")
    assert err.value.status == 400
    db.execute("UPDATE listings SET allow_test_drive = 0")
    with pytest.raises(LabError) as err:
        proofs.test_drive(listing, "v_x")
    assert err.value.status == 403 and err.value.code == "test_drive_off"


def test_proof_checks_are_rate_limited(fake_market, monkeypatch):
    monkeypatch.setenv("RATE_PROOFS_PER_HOUR", "2")
    from parable.config import get_settings

    get_settings.cache_clear()
    ada = make_account("Ada")
    _, _, _, listing = headline(ada, fake_market)
    proofs.rerun_listing(listing, "v_visitor0000000a")
    proofs.test_drive(listing, "v_visitor0000000a")
    with pytest.raises(LabError) as err:
        proofs.rerun_listing(listing, "v_visitor0000000a")
    assert err.value.status == 429
    proofs.rerun_listing(listing, "v_visitor0000000b")


def test_rerun_and_test_drive_refuse_paused_listings(fake_market):
    ada = make_account("Ada")
    _, _, _, listing = headline(ada, fake_market)
    db.execute("UPDATE listings SET active = 0 WHERE id = ?", (listing,))
    for call in (lambda: proofs.rerun_listing(listing, "v_visitor0000000b"),
                 lambda: proofs.test_drive(listing, "v_visitor0000000b")):
        with pytest.raises(LabError) as err:
            call()
        assert err.value.status == 404 and err.value.code == "not_found"
    db.execute("UPDATE listings SET active = 1 WHERE id = ?", (listing,))
    assert proofs.rerun_listing(listing, "v_visitor0000000b")["match"] is True
