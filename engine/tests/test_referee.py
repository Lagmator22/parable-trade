import pytest

from parable import ledger, referee
from parable.db import execute
from parable.models import BotRules
from parable.referee import RefereeError

USD = 1_000_000


def rules(**overrides) -> BotRules:
    base = {"strategy": "momentum", "max_trade_usd": 250 * USD, "max_loss_bps": 300, "lease_seconds": 300}
    return BotRules(**{**base, **overrides})


def open_run(**overrides) -> dict:
    return referee.open_run("s_test", rules(**overrides), "practice", "Test bot")


def refusal_reason(run_id: int, *args) -> str:
    with pytest.raises(RefereeError) as caught:
        referee.trade(run_id, *args)
    return caught.value.reason


def kinds(subject: str) -> list[str]:
    return [e["kind"] for e in ledger.entries(subject=subject)][::-1]


def test_open_run_persists_and_logs(price_box):
    run = open_run()
    assert run["status"] == "alive"
    assert run["cash_usd"] == run["start_cash_usd"] == 1000 * USD
    assert run["eth_wei"] == 0
    assert run["fingerprint"].startswith("0x")
    assert run["rules"]["max_trade_usd"] == 250 * USD
    assert kinds(f"run:{run['id']}") == ["run.started"]
    started = ledger.entries(kind="run.started")[0]["data"]
    assert started["fingerprint"] == run["fingerprint"]
    assert started["rules"]["strategy"] == "momentum"


def test_open_run_rejects_unknown_purpose(price_box):
    with pytest.raises(ValueError):
        referee.open_run("s_test", rules(), "demo", "x")


def test_buy_fills_with_integer_math(price_box):
    run = open_run()
    result = referee.trade(run["id"], "buy", 100 * USD, "dip")
    assert result["eth_wei"] == 100 * USD * 10**20 // (3000 * 10**8)
    assert result["cash_usd"] == 900 * USD
    assert result["price"] == 3000 * 10**8
    assert result["equity_after"] == 900 * USD + result["eth_wei"] * 3000 * 10**8 // 10**20
    live = referee.get_run(run["id"])
    assert live["trades"] == 1 and live["cash_usd"] == 900 * USD


def test_sell_converts_eth_back_to_cash(price_box):
    run = open_run()
    referee.trade(run["id"], "buy", 200 * USD, "in")
    price_box.set(3300)
    sold = referee.trade(run["id"], "sell", 110 * USD, "out")
    assert sold["cash_usd"] == 800 * USD + 110 * USD
    assert referee.equity(run["id"]) == pytest.approx(1020 * USD, abs=2)


def test_round_trip_at_same_price_never_creates_money(price_box):
    price_box.set(3123.456789)
    run = open_run()
    referee.trade(run["id"], "buy", 250 * USD, "in")
    referee.trade(run["id"], "sell", 250 * USD - 1, "out")
    assert referee.equity(run["id"]) <= 1000 * USD
    assert referee.get_run(run["id"])["eth_wei"] >= 0


def test_trade_is_written_to_ledger(price_box):
    run = open_run()
    referee.trade(run["id"], "buy", 50 * USD, "because")
    entry = ledger.entries(subject=f"run:{run['id']}", kind="run.trade")[0]["data"]
    assert entry["side"] == "buy" and entry["amount_usd"] == 50 * USD
    assert entry["reason"] == "because" and entry["price"] == 3000 * 10**8
    assert entry["equity_after"] > 0


def test_over_trade_limit_is_refused_and_logged(price_box):
    run = open_run()
    assert refusal_reason(run["id"], "buy", 251 * USD, "greedy") == "OverTradeLimit"
    live = referee.get_run(run["id"])
    assert live["refusals"] == 1 and live["trades"] == 0 and live["cash_usd"] == 1000 * USD
    refused = ledger.entries(subject=f"run:{run['id']}", kind="run.refused")
    assert len(refused) == 1
    assert refused[0]["data"]["reason"] == "OverTradeLimit"
    assert refused[0]["data"]["bot_reason"] == "greedy"


def test_exactly_at_limit_is_allowed(price_box):
    run = open_run()
    assert referee.trade(run["id"], "buy", 250 * USD, "max")["cash_usd"] == 750 * USD


def test_insufficient_cash(price_box):
    run = open_run(max_trade_usd=600 * USD, max_loss_bps=9000)
    referee.trade(run["id"], "buy", 600 * USD, "a")
    assert refusal_reason(run["id"], "buy", 500 * USD, "b") == "InsufficientCash"
    assert referee.get_run(run["id"])["refusals"] == 1


def test_insufficient_eth(price_box):
    run = open_run()
    assert refusal_reason(run["id"], "sell", 10 * USD, "nothing to sell") == "InsufficientEth"
    referee.trade(run["id"], "buy", 100 * USD, "in")
    assert refusal_reason(run["id"], "sell", 101 * USD, "too much") == "InsufficientEth"
    assert referee.trade(run["id"], "sell", 100 * USD - 1, "ok")["eth_wei"] < 10**9


@pytest.mark.parametrize("amount", [0, -5, 1.5, "10", None, True])
def test_bad_amounts(price_box, amount):
    run = open_run()
    assert refusal_reason(run["id"], "buy", amount, "bad") == "BadAmount"
    assert referee.get_run(run["id"])["refusals"] == 1


def test_bad_side(price_box):
    run = open_run()
    assert refusal_reason(run["id"], "short", 10 * USD, "bad") == "BadAmount"


def test_reason_is_truncated(price_box):
    run = open_run()
    referee.trade(run["id"], "buy", USD, "x" * 5000)
    stored = ledger.entries(subject=f"run:{run['id']}", kind="run.trade")[0]["data"]["reason"]
    assert len(stored) == referee.REASON_LIMIT


def test_expiry_ends_run_and_blocks_trades(price_box, monkeypatch):
    run = open_run(lease_seconds=60)
    referee.trade(run["id"], "buy", 100 * USD, "in")
    monkeypatch.setattr(referee, "now", lambda: run["expires_at"] + 1)
    assert refusal_reason(run["id"], "buy", USD, "late") == "Expired"
    ended = referee.get_run(run["id"])
    assert ended["status"] == "dead" and ended["cause"] == "expired"
    assert ended["final_equity_usd"] == pytest.approx(1000 * USD, abs=2)
    assert refusal_reason(run["id"], "buy", USD, "later") == "NotAlive"


def test_check_ends_expired_run_once(price_box, monkeypatch):
    run = open_run(lease_seconds=60)
    assert referee.check(run["id"]) is None
    monkeypatch.setattr(referee, "now", lambda: run["expires_at"])
    ended = referee.check(run["id"])
    assert ended["cause"] == "expired"
    assert referee.check(run["id"]) is None
    assert kinds(f"run:{run['id']}").count("run.ended") == 1


def test_run_ended_ledger_entry_contents(price_box, monkeypatch):
    run = open_run(lease_seconds=60)
    referee.trade(run["id"], "buy", 100 * USD, "in")
    refusal_reason(run["id"], "buy", 900 * USD, "over")
    price_box.set(3300)
    monkeypatch.setattr(referee, "now", lambda: run["started_at"] + 60)
    referee.check(run["id"])
    data = ledger.entries(kind="run.ended")[0]["data"]
    assert data["cause"] == "expired"
    assert data["trades"] == 1 and data["refusals"] == 1
    assert data["lifetime_s"] == 60
    assert data["return_bps"] == (data["final_equity_usd"] - 1000 * USD) * 10_000 // (1000 * USD)
    assert data["return_bps"] == 99


def test_loss_limit_triggers_on_drawdown(price_box):
    run = open_run(max_trade_usd=1000 * USD, max_loss_bps=300)
    referee.trade(run["id"], "buy", 1000 * USD, "all in")
    price_box.set(2920)
    assert referee.check(run["id"]) is None
    price_box.set(2900)
    ended = referee.check(run["id"])
    assert ended["cause"] == "loss_limit"
    assert ended["final_equity_usd"] < 970 * USD


def test_loss_limit_boundary_is_inclusive(price_box):
    run = open_run(max_trade_usd=1000 * USD, max_loss_bps=1000)
    referee.trade(run["id"], "buy", 1000 * USD, "all in")
    price_box.set(2700.1)
    assert referee.check(run["id"]) is None
    price_box.set(2700)
    assert referee.check(run["id"])["cause"] == "loss_limit"


def test_drawdown_is_measured_from_peak_not_start(price_box):
    run = open_run(max_trade_usd=1000 * USD, max_loss_bps=300)
    referee.trade(run["id"], "buy", 1000 * USD, "all in")
    price_box.set(3300)
    assert referee.check(run["id"]) is None
    assert referee.get_run(run["id"])["peak_equity_usd"] > 1090 * USD
    price_box.set(3190)
    ended = referee.check(run["id"])
    assert ended["cause"] == "loss_limit"
    assert ended["final_equity_usd"] > 1000 * USD


def test_get_run_derived_fields(price_box):
    run = open_run(max_trade_usd=1000 * USD, max_loss_bps=2000)
    referee.trade(run["id"], "buy", 1000 * USD, "all in")
    price_box.set(3300)
    referee.check(run["id"])
    price_box.set(3150)
    live = referee.get_run(run["id"])
    assert live["equity_usd"] == pytest.approx(1050 * USD, abs=2)
    assert live["pnl_bps"] in (499, 500)
    assert live["drawdown_bps"] in (454, 455)
    assert 0 < live["seconds_left"] <= 300


def test_stop_ends_run_and_is_idempotent(price_box):
    run = open_run()
    first = referee.stop(run["id"])
    assert first["status"] == "dead" and first["cause"] == "stopped"
    again = referee.stop(run["id"], "loss_limit")
    assert again["cause"] == "stopped"
    assert kinds(f"run:{run['id']}").count("run.ended") == 1


def test_stop_rejects_unknown_cause(price_box):
    run = open_run()
    with pytest.raises(ValueError):
        referee.stop(run["id"], "boredom")


def test_dead_run_rejects_trades_without_new_records(price_box):
    run = open_run()
    referee.stop(run["id"])
    before = ledger.head()
    assert refusal_reason(run["id"], "buy", USD, "zombie") == "NotAlive"
    assert ledger.head() == before
    assert referee.get_run(run["id"])["refusals"] == 0


def test_unknown_run_raises(price_box):
    with pytest.raises(referee.RunNotFound):
        referee.get_run(404)
    with pytest.raises(referee.RunNotFound):
        referee.trade(404, "buy", USD, "x")


def test_end_hook_fires_once_with_final_run(price_box):
    seen = []
    referee.add_end_hook(seen.append)
    referee.add_end_hook(seen.append)
    run = open_run()
    referee.stop(run["id"])
    referee.stop(run["id"])
    referee.check(run["id"])
    assert len(seen) == 1
    assert seen[0]["id"] == run["id"] and seen[0]["cause"] == "stopped"
    assert seen[0]["final_equity_usd"] == 1000 * USD


def test_failing_end_hook_does_not_break_others(price_box):
    seen = []

    def explode(run):
        raise RuntimeError("boom")

    referee.add_end_hook(explode)
    referee.add_end_hook(seen.append)
    run = open_run()
    referee.stop(run["id"])
    assert len(seen) == 1


def test_trade_hitting_expiry_announces_end(price_box, monkeypatch):
    seen = []
    referee.add_end_hook(seen.append)
    run = open_run(lease_seconds=60)
    monkeypatch.setattr(referee, "now", lambda: run["expires_at"] + 5)
    refusal_reason(run["id"], "buy", USD, "late")
    assert [r["cause"] for r in seen] == ["expired"]


def test_list_runs_filters_and_orders(price_box):
    first = referee.open_run("s_a", rules(), "practice", "one")
    second = referee.open_run("s_b", rules(), "probation", "two")
    third = referee.open_run("s_a", rules(), "practice", "three")
    referee.stop(first["id"])
    assert [r["id"] for r in referee.list_runs()] == [third["id"], second["id"], first["id"]]
    assert [r["id"] for r in referee.list_runs(seller_id="s_a")] == [third["id"], first["id"]]
    assert [r["id"] for r in referee.list_runs(status="dead")] == [first["id"]]
    assert [r["id"] for r in referee.list_runs(purpose="probation")] == [second["id"]]
    assert len(referee.list_runs(limit=1)) == 1


def test_seller_record_for_new_seller(price_box):
    record = referee.seller_record("s_nobody")
    assert record["runs"] == 0 and record["survival_rate"] == 0.0
    assert record["worst_return_bps"] == 0 and record["avg_return_bps"] == 0


def test_seller_record_aggregates(price_box, monkeypatch):
    winner = referee.open_run("s_a", rules(max_trade_usd=1000 * USD), "practice", "w")
    referee.trade(winner["id"], "buy", 1000 * USD, "in")
    price_box.set(3030)
    monkeypatch.setattr(referee, "now", lambda: winner["expires_at"])
    referee.check(winner["id"])
    monkeypatch.undo()
    price_box.set(3000)
    loser = referee.open_run("s_a", rules(max_trade_usd=1000 * USD), "practice", "l")
    referee.trade(loser["id"], "buy", 1000 * USD, "in")
    refusal_reason(loser["id"], "buy", 5000 * USD, "over")
    price_box.set(2800)
    referee.check(loser["id"])
    stopped = referee.open_run("s_a", rules(), "practice", "s")
    referee.stop(stopped["id"])
    referee.open_run("s_a", rules(), "practice", "still alive")
    referee.open_run("s_other", rules(), "practice", "someone else")
    record = referee.seller_record("s_a")
    assert record["runs"] == 4 and record["alive"] == 1 and record["ended"] == 3
    assert record["survived"] == 1 and record["loss_limit"] == 1 and record["stopped"] == 1
    assert record["survival_rate"] == pytest.approx(1 / 3)
    assert record["best_return_bps"] in (99, 100) and record["worst_return_bps"] < -600
    assert record["total_trades"] == 2 and record["total_refusals"] == 1
    assert record["practice_runs"] == 4 and record["probation_runs"] == 0


def test_seller_record_counts_probation_against_listing_threshold(price_box, monkeypatch):
    for listing_id, minimum in (("l_easy", 0), ("l_hard", 500)):
        execute("INSERT INTO listings (id, seller_id, min_return_bps, active) VALUES (?, 's_a', ?, 1)",
                (listing_id, minimum))
    runs = {}
    for listing_id in ("l_easy", "l_hard"):
        runs[listing_id] = referee.open_run("s_a", rules(max_trade_usd=1000 * USD), "probation", listing_id,
                                            listing_id=listing_id)
        referee.trade(runs[listing_id]["id"], "buy", 1000 * USD, "in")
    price_box.set(3030)
    monkeypatch.setattr(referee, "now", lambda: runs["l_easy"]["expires_at"])
    referee.check(runs["l_easy"]["id"])
    referee.check(runs["l_hard"]["id"])
    record = referee.seller_record("s_a")
    assert record["probation_runs"] == 2
    assert record["probation_passed"] == 1 and record["probation_failed"] == 1
