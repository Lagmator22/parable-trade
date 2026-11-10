import pytest

from parable import ledger, referee
from parable.db import execute
from parable.models import BotRules
from parable.referee import RefereeError
from parable.referee_math import sell_amount
from run_support import PRICE, SYMBOL, agent_run, feed

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


def order(run_id: int, side: str, amount: int, **kw) -> dict:
    return referee.place_order(run_id, side, amount, "test", **kw)


def order_refusal(run_id: int, *args, **kw) -> str:
    with pytest.raises(RefereeError) as caught:
        order(run_id, *args, **kw)
    return caught.value.reason


def test_agent_run_columns_view_and_ledger(price_box):
    run = agent_run()
    assert run["version_id"] == "v_test000001" and run["symbol"] == SYMBOL and run["quote"] == "USDT"
    assert run["units"] == 0 and run["cash_usd"] == 1000 * USD and run["spec_hash"] == "ab" * 32
    assert "rules_json" not in run and run["rules"]["max_trade"] == 1000 * USD
    started = ledger.entries(subject=f"run:{run['id']}")[0]
    assert started["kind"] == "run.started" and started["data"]["version_id"] == "v_test000001"


def test_track_purpose_is_allowed(price_box):
    assert agent_run("track")["purpose"] == "track"


def test_legacy_run_has_no_version(price_box):
    assert open_run()["version_id"] is None


def test_buy_integer_math_with_fee_and_slippage(price_box):
    run = agent_run()
    done = order(run["id"], "buy", 100 * USD, fee_bps=10, slippage_bps=5)
    assert done["price"] == 300150000000 and done["units_delta"] == 3331667 and done["fee"] == 100_000
    after = referee.get_run(run["id"])
    assert after["cash_usd"] == 1000 * USD - 100 * USD - 100_000
    assert after["units"] == 3331667 and after["entry_price"] == 300150000000 and after["high_water"] == 300150000000
    assert after["equity_usd"] == after["cash_usd"] + 3331667 * PRICE // 10**10


def test_sell_all_rounds_up_caps_and_clears_position(price_box):
    run = agent_run()
    order(run["id"], "buy", 100 * USD)
    held = referee.load(run["id"])["units"]
    done = order(run["id"], "sell", sell_amount(held, PRICE), fee_bps=10)
    flat = referee.load(run["id"])
    assert flat["units"] == 0 and flat["entry_price"] == 0 and flat["high_water"] == 0
    assert done["units_delta"] == -held and done["amount"] <= 100 * USD
    assert flat["cash_usd"] <= 1000 * USD


def test_round_trip_never_creates_money_with_zero_costs(price_box):
    run = agent_run()
    for _ in range(5):
        order(run["id"], "buy", 333_333 * 3 + 1)
        order(run["id"], "sell", sell_amount(referee.load(run["id"])["units"], PRICE))
    assert referee.load(run["id"])["cash_usd"] <= 1000 * USD


def test_ledger_trade_data_for_agent_run(price_box):
    run = agent_run()
    order(run["id"], "buy", 10 * USD, fee_bps=10)
    data = ledger.entries(subject=f"run:{run['id']}")[0]["data"]
    assert set(data) == {"side", "amount", "price", "units_delta", "fee", "reason", "equity_after"}


def test_refusals_for_agent_runs(price_box):
    run = agent_run(max_trade=100 * USD)
    rid = run["id"]
    assert order_refusal(rid, "buy", 0) == "BadAmount"
    assert order_refusal(rid, "buy", 1.5) == "BadAmount"
    assert order_refusal(rid, "hold", 5) == "BadAmount"
    assert order_refusal(rid, "buy", 101 * USD) == "OverTradeLimit"
    assert order_refusal(rid, "sell", 5 * USD) == "InsufficientUnits"
    assert referee.load(rid)["refusals"] == 5
    assert referee.load(rid)["trades"] == 0


def test_buy_needs_amount_plus_fee_in_cash(price_box):
    run = agent_run(start_cash=100 * USD)
    assert order_refusal(run["id"], "buy", 100 * USD, fee_bps=10) == "InsufficientCash"
    assert order(run["id"], "buy", 99_900_099, fee_bps=10)["fee"] == 99_900


def test_sells_are_exempt_from_max_trade(price_box):
    run = agent_run(max_trade=100 * USD)
    order(run["id"], "buy", 100 * USD)
    assert order(run["id"], "sell", 500 * USD)["units_delta"] < 0


def test_buy_below_one_unit_is_refused(price_box):
    assert order_refusal(agent_run()["id"], "buy", 1) == "BadAmount"


def test_stopped_agent_run_refuses_orders(price_box):
    run = agent_run()
    referee.stop(run["id"])
    assert order_refusal(run["id"], "buy", USD) == "NotAlive"


def test_agent_run_expiry_blocks_order_and_announces(price_box, monkeypatch):
    run = agent_run(lease_seconds=60)
    seen = []
    referee.add_end_hook(seen.append)
    monkeypatch.setattr(referee, "now", lambda: run["started_at"] + 61)
    assert order_refusal(run["id"], "buy", USD) == "Expired"
    assert [r["cause"] for r in seen] == ["expired"]


def test_agent_loss_limit_ends_run(price_box):
    run = agent_run(max_loss_bps=500)
    order(run["id"], "buy", 1000 * USD)
    price_box.set(2800)
    ended = referee.check(run["id"])
    assert ended["cause"] == "loss_limit" and ended["status"] == "dead"


def test_mark_only_raises_high_water(price_box):
    run = agent_run()
    order(run["id"], "buy", 100 * USD)
    referee.mark(run["id"], price=PRICE * 2)
    referee.mark(run["id"], price=PRICE)
    assert referee.load(run["id"])["high_water"] == PRICE * 2
    referee.mark(run["id"], last_bar_t=1234)
    assert referee.load(run["id"])["last_bar_t"] == 1234


def test_record_point_and_points(price_box):
    run = agent_run()
    referee.record_point(run["id"], PRICE)
    order(run["id"], "buy", 100 * USD)
    referee.record_point(run["id"], PRICE * 2)
    found = referee.points(run["id"])
    assert [p[1:] for p in found] == [[1000 * USD, PRICE], [900 * USD + 3333333 * PRICE * 2 // 10**10, PRICE * 2]]
    assert referee.points(run["id"], since=found[-1][0] + 1) == []


def test_points_are_downsampled_keeping_ends(price_box):
    run = agent_run()
    for i in range(50):
        execute("INSERT INTO run_points (run_id, t, equity, price) VALUES (?,?,?,?)", (run["id"], i, i, i))
    found = referee.points(run["id"], limit=10)
    assert len(found) == 10 and found[0][0] == 0 and found[-1][0] == 49
    assert referee.points(run["id"], limit=1) == [[49, 49, 49]]
    assert len(referee.points(run["id"], limit=500)) == 50


def test_run_points_cap_drops_oldest_tenth(price_box, monkeypatch):
    from parable.config import get_settings
    monkeypatch.setenv("MAX_RUN_POINTS_PER_RUN", "20")
    get_settings.cache_clear()
    run = agent_run()
    for i in range(20):
        execute("INSERT INTO run_points (run_id, t, equity, price) VALUES (?,?,?,?)", (run["id"], i, i, i))
    referee.record_point(run["id"], PRICE)
    found = referee.points(run["id"], limit=100)
    assert len(found) == 19 and found[0][0] == 2


def test_public_reads_never_touch_the_provider(feed):
    run = agent_run()
    referee.record_point(run["id"], PRICE)
    feed.calls = 0
    assert referee.get_run(run["id"])["equity_usd"] == 1000 * USD
    assert len(referee.list_runs()) == 1 and referee.points(run["id"])
    assert referee.seller_record("s_test")["runs"] == 1
    assert feed.calls == 0


def test_view_uses_cached_quote_then_last_point_then_break_even(feed):
    from parable.lab import markets
    run = agent_run()
    assert referee.get_run(run["id"])["equity_usd"] == 1000 * USD
    markets.latest(SYMBOL)
    feed.calls = 0
    execute("UPDATE runs SET cash_usd = 0, units = 333333333, entry_price = ? WHERE id = ?", (PRICE, run["id"]))
    assert referee.get_run(run["id"])["equity_usd"] == 333333333 * 3000 * 10**8 // 10**10
    assert feed.calls == 0
    markets.reset_providers(offline=True)
    markets.register_provider(feed)
    execute("INSERT INTO run_points (run_id, t, equity, price) VALUES (?,?,?,?)", (run["id"], 1, 1, PRICE * 2))
    assert referee.get_run(run["id"])["equity_usd"] == 333333333 * 6000 * 10**8 // 10**10
    execute("DELETE FROM run_points")
    assert referee.get_run(run["id"])["equity_usd"] == 333333333 * 3000 * 10**8 // 10**10
    assert feed.calls == 0


def test_seller_record_counts_track_runs_separately(price_box):
    live = agent_run("track")
    early = agent_run("track")
    agent_run("practice")
    referee.stop(early["id"])
    record = referee.seller_record("s_test")
    assert record["track_runs"] == 2 and record["track_ended_early"] == 1 and record["practice_runs"] == 1
    assert record["alive"] == 2 and live["status"] == "alive"
