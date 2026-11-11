import json

import pytest

from agents_support import SYMBOL, INTERVAL, add_listing, clean_lab, make_account, new_agent, new_version, spec_dict
from lab_support import fake_market, make_bars
from parable import agents, db
from parable.errors import LabError
from parable.lab import datasets
from parable.lab.spec import SpecError, parse_spec


def test_create_agent_validates_and_limits(monkeypatch):
    owner = make_account()
    agent = agents.create_agent(owner["id"], "  Alpha  ", SYMBOL, INTERVAL)
    assert agent["id"].startswith("a_") and agent["name"] == "Alpha" and agent["status"] == "draft"
    for args in (("", SYMBOL, INTERVAL), ("x", "BTCUSDT", INTERVAL), ("x", SYMBOL, "7m")):
        with pytest.raises(LabError) as err:
            agents.create_agent(owner["id"], *args)
        assert err.value.status == 400
    monkeypatch.setenv("MAX_AGENTS_PER_ACCOUNT", "1")
    from parable.config import get_settings

    get_settings.cache_clear()
    with pytest.raises(LabError) as err:
        agents.create_agent(owner["id"], "Beta", SYMBOL, INTERVAL)
    assert err.value.status == 409


def test_owned_agent_and_version_idor():
    ada, bob = make_account("Ada"), make_account("Bob")
    agent = new_agent(ada)
    version = new_version(ada, agent)
    assert agents.owned_agent(ada["id"], agent["id"])["id"] == agent["id"]
    with pytest.raises(LabError) as err:
        agents.owned_agent(bob["id"], agent["id"])
    assert err.value.status == 403
    with pytest.raises(LabError) as err:
        agents.owner_version(bob["id"], version["id"])
    assert err.value.status == 403
    with pytest.raises(LabError) as err:
        agents.owned_agent(ada["id"], "a_nope")
    assert err.value.status == 404
    with pytest.raises(LabError):
        agents.save_version(bob["id"], agent["id"], parse_spec(spec_dict()))


def test_versions_increment_and_are_idempotent():
    owner = make_account()
    agent = new_agent(owner)
    first = new_version(owner, agent)
    again = new_version(owner, agent, name="Renamed only")
    assert again["id"] == first["id"] and first["n"] == 1
    changed = new_version(owner, agent, stop_loss_pct=9.0)
    assert changed["n"] == 2 and changed["id"] != first["id"]
    assert agents.owned_agent(owner["id"], agent["id"])["latest_version_id"] == changed["id"]
    assert changed["spec"]["stop_loss_pct"] == 9.0 and changed["steps_text"] == "buy dips"


def test_save_version_built_by_and_limits(monkeypatch):
    owner = make_account()
    agent = new_agent(owner)
    saved = agents.save_version(owner["id"], agent["id"], parse_spec(spec_dict()), "x" * 9000, "template:trend")
    assert saved["built_by"] == "template:trend" and len(saved["steps_text"]) == 4000
    monkeypatch.setenv("MAX_VERSIONS_PER_AGENT", "1")
    from parable.config import get_settings

    get_settings.cache_clear()
    with pytest.raises(LabError) as err:
        new_version(owner, agent, stop_loss_pct=3.0)
    assert err.value.status == 409
    with pytest.raises(SpecError):
        agents.save_version(owner["id"], agent["id"], parse_spec(spec_dict(entry="close >")))


def test_spec_text_lives_only_in_versions_table():
    owner = make_account()
    agent = new_agent(owner)
    version = new_version(owner, agent)
    entry = version["spec"]["entry"]
    view = agents.agent_view(agents.owned_agent(owner["id"], agent["id"]), agents.version_summaries(agent["id"]))
    assert entry not in json.dumps(view) and "spec" not in view["versions"][0]
    summaries = agents.list_agents(owner["id"])
    assert summaries[0]["version_count"] == 1 and entry not in json.dumps(summaries)
    assert agents.agent_version(owner["id"], agent["id"], version["id"])["spec"]["entry"] == entry
    other = new_agent(owner, "Other")
    with pytest.raises(LabError) as err:
        agents.agent_version(owner["id"], other["id"], version["id"])
    assert err.value.status == 404


def test_delete_agent_rules():
    owner = make_account()
    agent = new_agent(owner)
    version = new_version(owner, agent)
    add_listing(owner, version["id"])
    with pytest.raises(LabError) as err:
        agents.delete_agent(owner["id"], agent["id"])
    assert err.value.status == 409
    plain = new_agent(owner, "Plain")
    new_version(owner, plain, stop_loss_pct=4.0)
    agents.delete_agent(owner["id"], plain["id"])
    assert db.one("SELECT 1 AS x FROM agents WHERE id = ?", (plain["id"],)) is None
    db.execute("UPDATE agents SET status = 'listed' WHERE id = ?", (agent["id"],))
    with pytest.raises(LabError) as err:
        agents.delete_agent(owner["id"], agent["id"])
    assert err.value.status == 409
    bob = make_account("Bob")
    with pytest.raises(LabError) as err:
        agents.delete_agent(bob["id"], agent["id"])
    assert err.value.status == 403


def test_entitled_owner_and_buyers():
    seller, buyer, other = make_account("S"), make_account("B"), make_account("O")
    agent = new_agent(seller)
    version = new_version(seller, agent)
    listing = add_listing(seller, version["id"])
    assert agents.entitled(seller["id"], version["id"]) and not agents.entitled(buyer["id"], version["id"])
    assert not agents.entitled(None, version["id"])
    for status, expected in (("created", False), ("captured", True), ("paid_out", True), ("refunded", False)):
        db.execute("DELETE FROM purchases")
        db.execute("INSERT INTO purchases (id, listing_id, buyer_id, status) VALUES (?, ?, ?, ?)",
                   ("p_" + status, listing, buyer["id"], status))
        assert agents.entitled(buyer["id"], version["id"]) is expected
        assert not agents.entitled(other["id"], version["id"])


def test_resolve_bars_market_and_errors(fake_market):
    bars, kind = agents.resolve_bars(None, SYMBOL, INTERVAL, limit=100)
    assert len(bars) == 100 and kind == "market"
    with pytest.raises(LabError) as err:
        agents.resolve_bars(None, SYMBOL, INTERVAL, limit=10)
    assert err.value.status == 400
    with pytest.raises(LabError):
        agents.resolve_bars(None, SYMBOL, INTERVAL, limit=999999)
    with pytest.raises(LabError):
        agents.resolve_bars(None, "fake:NOPE", INTERVAL)


def test_resolve_bars_upload_requires_owner(fake_market):
    ada, bob = make_account("Ada"), make_account("Bob")
    stored = datasets.store_dataset(ada["id"], "Mine", "USD", make_bars(60, interval_s=86400), "1d")
    bars, kind = agents.resolve_bars(ada["id"], stored["symbol"], "1d")
    assert len(bars) == 60 and kind == "creator"
    by_id, _ = agents.resolve_bars(ada["id"], "ignored:x", "1d", dataset_id=stored["id"])
    assert by_id == bars
    for who, expected in ((bob["id"], 403), (None, 401)):
        for kwargs in ({"symbol": stored["symbol"]}, {"symbol": SYMBOL, "dataset_id": stored["id"]}):
            with pytest.raises(LabError) as err:
                agents.resolve_bars(who, kwargs["symbol"], "1d", dataset_id=kwargs.get("dataset_id"))
            assert err.value.status == expected
    with pytest.raises(LabError) as err:
        agents.resolve_bars(ada["id"], stored["symbol"], "1h")
    assert err.value.status == 400
    with pytest.raises(LabError):
        agents.resolve_bars(ada["id"], "upload:d_other00000", "1d", dataset_id=stored["id"])


def test_resolve_bars_trims_to_range(fake_market):
    ada = make_account("Ada")
    bars = make_bars(80, interval_s=86400)
    stored = datasets.store_dataset(ada["id"], "Mine", "USD", bars, "1d")
    cut, _ = agents.resolve_bars(ada["id"], stored["symbol"], "1d", start=bars[10][0], end=bars[50][0])
    assert cut[0][0] == bars[10][0] and cut[-1][0] == bars[49][0]
