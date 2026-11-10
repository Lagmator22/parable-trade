import json

from parable import ledger
from parable.db import execute, rows


def fill(count: int) -> list[dict]:
    return [ledger.append("run.trade", f"run:{i % 2}", {"n": i}) for i in range(count)]


def test_empty_ledger_head_and_verify():
    assert ledger.head() == {"seq": 0, "hash": ledger.GENESIS}
    assert ledger.verify() == {"ok": True, "checked": 0, "first_bad_seq": None, "head": ledger.GENESIS}
    assert ledger.entries() == []


def test_entry_hash_matches_spec_formula():
    first = ledger.append("seller.joined", "seller:s_1", {"name": "A"})
    data_json = json.dumps({"name": "A"}, sort_keys=True, separators=(",", ":"))
    expected = ledger.entry_hash(1, first["at"], "seller.joined", "seller:s_1", data_json, ledger.GENESIS)
    assert first["hash"] == expected
    assert first["seq"] == 1 and first["prev_hash"] == ledger.GENESIS
    assert first["data"] == {"name": "A"}


def test_chain_links_each_entry_to_previous():
    made = fill(4)
    for before, after in zip(made, made[1:]):
        assert after["prev_hash"] == before["hash"]
        assert after["seq"] == before["seq"] + 1
    assert ledger.head() == {"seq": 4, "hash": made[-1]["hash"]}
    assert ledger.verify() == {"ok": True, "checked": 4, "first_bad_seq": None, "head": made[-1]["hash"]}


def test_entries_newest_first_with_filters_and_paging():
    fill(6)
    ledger.append("run.ended", "run:0", {"cause": "expired"})
    newest = ledger.entries()
    assert [e["seq"] for e in newest] == [7, 6, 5, 4, 3, 2, 1]
    assert [e["seq"] for e in ledger.entries(subject="run:1")] == [6, 4, 2]
    assert [e["kind"] for e in ledger.entries(kind="run.ended")] == ["run.ended"]
    assert [e["seq"] for e in ledger.entries(limit=2)] == [7, 6]
    assert [e["seq"] for e in ledger.entries(before_seq=4)] == [3, 2, 1]
    assert ledger.entries(subject="run:0", kind="run.ended", before_seq=7) == []


def test_verify_detects_edited_data():
    fill(5)
    execute("UPDATE ledger SET data_json = ? WHERE seq = 3", ('{"n":999}',))
    result = ledger.verify()
    assert result["ok"] is False
    assert result["first_bad_seq"] == 3


def test_verify_detects_edited_kind_and_timestamp():
    fill(3)
    execute("UPDATE ledger SET kind = 'run.refused' WHERE seq = 2")
    assert ledger.verify()["first_bad_seq"] == 2
    execute("UPDATE ledger SET kind = 'run.trade' WHERE seq = 2")
    assert ledger.verify()["ok"] is True
    execute("UPDATE ledger SET at = at + 1 WHERE seq = 1")
    assert ledger.verify()["first_bad_seq"] == 1


def test_verify_detects_deleted_middle_entry():
    fill(5)
    execute("DELETE FROM ledger WHERE seq = 3")
    result = ledger.verify()
    assert result["ok"] is False
    assert result["first_bad_seq"] == 4


def test_verify_detects_deleted_first_entry():
    fill(3)
    execute("DELETE FROM ledger WHERE seq = 1")
    assert ledger.verify()["first_bad_seq"] == 2


def test_verify_detects_rewritten_link_even_with_consistent_hash():
    fill(3)
    row = rows("SELECT * FROM ledger WHERE seq = 3")[0]
    forged_prev = "f" * 64
    forged_hash = ledger.entry_hash(3, row["at"], row["kind"], row["subject"], row["data_json"], forged_prev)
    execute("UPDATE ledger SET prev_hash = ?, hash = ? WHERE seq = 3", (forged_prev, forged_hash))
    assert ledger.verify()["first_bad_seq"] == 3


def test_verify_accepts_rows_with_parsed_data():
    fill(3)
    parsed = ledger.entries(limit=10)[::-1]
    assert ledger.verify(parsed)["ok"] is True
    parsed[1]["data"]["n"] = 42
    assert ledger.verify(parsed)["first_bad_seq"] == 2


def test_verify_of_explicit_empty_list():
    assert ledger.verify([])["ok"] is True


def test_tamper_demo_rewrites_loss_limit_in_memory_only():
    ledger.append("run.started", "run:1", {})
    ledger.append("run.ended", "run:1", {"cause": "loss_limit", "final_equity_usd": 900})
    ledger.append("run.trade", "run:2", {})
    before_head = ledger.head()
    demo = ledger.tamper_demo()
    assert demo["edited_seq"] == 2
    assert demo["before"]["cause"] == "loss_limit"
    assert demo["after"]["cause"] == "expired"
    assert demo["verify"]["ok"] is False
    assert demo["verify"]["first_bad_seq"] == 2
    assert ledger.head() == before_head
    assert ledger.verify()["ok"] is True


def test_tamper_demo_changes_final_equity_when_not_a_loss():
    ledger.append("run.ended", "run:1", {"cause": "expired", "final_equity_usd": 1000})
    demo = ledger.tamper_demo()
    assert demo["after"]["final_equity_usd"] > demo["before"]["final_equity_usd"]
    assert demo["verify"]["first_bad_seq"] == demo["edited_seq"]


def test_tamper_demo_without_run_ended_edits_last_entry():
    fill(3)
    demo = ledger.tamper_demo()
    assert demo["edited_seq"] == 3
    assert demo["verify"]["first_bad_seq"] == 3


def test_tamper_demo_on_empty_ledger():
    demo = ledger.tamper_demo()
    assert demo["edited_seq"] is None
    assert demo["verify"]["ok"] is True
