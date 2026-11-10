from parable.db import rows
from parable.referee_math import return_bps


def probation_passed(run: dict, thresholds: dict[str, int]) -> bool:
    threshold = thresholds.get(run["listing_id"], 0)
    return run["cause"] == "expired" and return_bps(run["start_cash_usd"], run["final_equity_usd"]) >= threshold


def seller_record(seller_id: str) -> dict:
    found = rows("SELECT * FROM runs WHERE seller_id = ?", (seller_id,))
    ended = [r for r in found if r["status"] == "dead"]
    returns = [return_bps(r["start_cash_usd"], r["final_equity_usd"]) for r in ended]
    survived = [r for r in ended if r["cause"] == "expired"]
    thresholds = {l["id"]: l["min_return_bps"] for l in rows(
        "SELECT id, min_return_bps FROM listings WHERE seller_id = ?", (seller_id,))}
    probations = [r for r in ended if r["purpose"] == "probation"]
    passed = [r for r in probations if probation_passed(r, thresholds)]
    tracks = [r for r in found if r["purpose"] == "track"]
    return {
        "runs": len(found),
        "alive": len(found) - len(ended),
        "ended": len(ended),
        "survived": len(survived),
        "loss_limit": sum(r["cause"] == "loss_limit" for r in ended),
        "stopped": sum(r["cause"] == "stopped" for r in ended),
        "survival_rate": len(survived) / len(ended) if ended else 0.0,
        "avg_return_bps": sum(returns) // len(returns) if returns else 0,
        "worst_return_bps": min(returns, default=0),
        "best_return_bps": max(returns, default=0),
        "total_trades": sum(r["trades"] for r in found),
        "total_refusals": sum(r["refusals"] for r in found),
        "practice_runs": sum(r["purpose"] == "practice" for r in found),
        "probation_runs": sum(r["purpose"] == "probation" for r in found),
        "probation_passed": len(passed),
        "probation_failed": len(probations) - len(passed),
        "track_runs": len(tracks),
        "track_ended_early": sum(r["status"] == "dead" and r["cause"] != "expired" for r in tracks),
    }
