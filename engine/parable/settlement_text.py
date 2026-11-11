import json

from parable import analyst, referee

MIN_EXPLANATION = 20
MAX_EXPLANATION = 300
MIN_TRADES = 1
MIN_BARS_SEEN = 3
CONTRADICTIONS = {True: ("voided", "never charged"), False: ("captured", "paid out", "paid to")}


def percent(bps: int) -> str:
    return f"{bps / 100:+.2f}%"


def duration(seconds: int) -> str:
    if seconds < 120:
        return f"{seconds} seconds"
    if seconds < 7200:
        return f"{seconds // 60} minutes"
    return f"{seconds / 3600:.1f} hours"


def build_verdict(run: dict, min_return_bps: int) -> dict:
    return_bps = referee.return_bps(run["start_cash_usd"], run["final_equity_usd"])
    bars_seen = run.get("bars_seen") or 0
    active_enough = run["trades"] >= MIN_TRADES and bars_seen >= MIN_BARS_SEEN
    return {
        "passed": run["cause"] == "expired" and return_bps >= min_return_bps and active_enough,
        "bars_seen": bars_seen,
        "min_trades": MIN_TRADES,
        "min_bars_seen": MIN_BARS_SEEN,
        "cause": run["cause"],
        "return_bps": return_bps,
        "min_return_bps": min_return_bps,
        "lifetime_s": run["lifetime_s"],
        "trades": run["trades"],
        "refusals": run["refusals"],
    }


def template_explanation(verdict: dict, trial_s: int) -> str:
    result, floor = percent(verdict["return_bps"]), percent(verdict["min_return_bps"])
    if verdict["passed"]:
        return (f"The agent survived the full {duration(trial_s)} trial and returned {result}, meeting the "
                f"promised minimum of {floor}, so the payment was captured.")
    if verdict["cause"] == "loss_limit":
        return (f"The agent hit its loss limit after {duration(verdict['lifetime_s'])} with a return of {result}, so "
                "the payment was voided and the buyer was never charged.")
    if verdict["cause"] == "stopped":
        return (f"The run was stopped after {duration(verdict['lifetime_s'])}, before the trial finished, so the "
                "payment was voided and the buyer was never charged.")
    if verdict["cause"] == "expired" and verdict["trades"] < verdict["min_trades"]:
        return ("The agent survived the trial but made no trades, so there was nothing to judge and the payment "
                "was voided and the buyer was never charged.")
    if verdict["cause"] == "expired" and verdict["bars_seen"] < verdict["min_bars_seen"]:
        return ("The agent saw too few market bars during the trial for the result to count, so the payment was "
                "voided and the buyer was never charged.")
    return (f"The agent survived the trial but returned {result}, below the promised minimum of {floor}, so the "
            "payment was voided and the buyer was never charged.")


def explanation_prompt(verdict: dict, listing: dict) -> str:
    facts = {
        "agent": listing["title"],
        "outcome": "passed" if verdict["passed"] else "failed",
        "ended_because": verdict["cause"],
        "return": percent(verdict["return_bps"]),
        "promised_minimum_return": percent(verdict["min_return_bps"]),
        "trial_length": duration(listing["trial_s"]),
        "lived_for": duration(verdict["lifetime_s"]),
        "trades": verdict["trades"],
        "refused_trades": verdict["refusals"],
    }
    return (
        "You explain the result of a paper-trading trial for a trading agent. The payment is captured only "
        "when the agent survives and meets its promised minimum return, otherwise it is voided. The decision is "
        "already made; never question or change it and use only the numbers given.\n"
        f"Facts: {json.dumps(facts)}\n"
        'Reply with JSON only: {"explanation": "<one plain-English sentence, at most 40 words>"}'
    )


def accept_explanation(answer: dict | None, passed: bool) -> str | None:
    text = answer.get("explanation") if answer else None
    if not isinstance(text, str):
        return None
    text = " ".join(text.split())
    lowered = text.lower()
    if not MIN_EXPLANATION <= len(text) <= MAX_EXPLANATION or "\n" in text:
        return None
    return None if any(word in lowered for word in CONTRADICTIONS[passed]) else text


def explain(verdict: dict, listing: dict) -> str:
    answer = analyst.ask(explanation_prompt(verdict, listing))
    return accept_explanation(answer, verdict["passed"]) or template_explanation(verdict, listing["trial_s"])
