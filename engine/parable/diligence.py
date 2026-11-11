import json
import re
import threading
import time

from parable import analyst
from parable.db import one
from parable.listing_views import listing_summary
from parable.listings import listing_row

CACHE_SECONDS = 60
MIN_TRADES = 10
DEEP_DRAWDOWN_PCT = 40
MIN_SPAN_DAYS = 30
TRACK_KEYS = ("equity_pct", "seconds", "runs_total", "runs_ended_early")
RISKS = ("low", "medium", "high")
CLAIM_PATTERN = re.compile(
    r"guarantee|risk[- ]free|no risk|can'?t lose|cannot lose|never lose|always win|100% (?:win|profit|safe)|sure thing",
    re.IGNORECASE)
NUMBER_PATTERN = re.compile(r"\d+(?:\.\d+)?")
MAX_HEADLINE = 160
MAX_LINE = 240

_cache: dict[str, tuple[float, tuple, dict]] = {}
_cache_lock = threading.Lock()


def pct(value: float) -> str:
    return f"{value * 100:.0f}%"


def bps_pct(bps: int) -> str:
    return f"{bps / 100:+.2f}%"


def gather_facts(listing: dict) -> dict:
    view = listing_summary(listing["id"])
    head = view["headline"]
    data = view["data"] or {}
    metrics = proof_metrics(listing["proof_id"])
    track = view["track"]
    span_days = round(((data.get("end") or 0) - (data.get("start") or 0)) / 86400, 1)
    return {
        "total_return_pct": metrics.get("total_return_pct"),
        "benchmark_return_pct": metrics.get("benchmark_return_pct"),
        "excess_return_pct": metrics.get("excess_return_pct"),
        "max_drawdown_pct": metrics.get("max_drawdown_pct"),
        "sharpe": metrics.get("sharpe"),
        "win_rate_pct": metrics.get("win_rate_pct"),
        "trades": head.get("trades") or 0,
        "exposure_pct": metrics.get("exposure_pct"),
        "bars": data.get("bars", 0),
        "source_kind": data.get("source_kind", ""),
        "span_days": span_days,
        "reruns": view["reruns"]["count"],
        "reruns_matched": view["reruns"]["matched"],
        "track": None if track is None else {key: track[key] for key in TRACK_KEYS},
        "seller_record": view["seller_record"],
        "price_cents": listing["price_cents"],
        "mode": listing["mode"],
        "trial_s": listing["trial_s"],
        "min_return_bps": listing["min_return_bps"],
        "allow_test_drive": bool(listing["allow_test_drive"]),
    }


def proof_metrics(proof_id: str) -> dict:
    found = one("SELECT metrics_json FROM proofs WHERE id = ?", (proof_id,))
    return json.loads(found["metrics_json"]) if found else {}


def pitch_flags(listing: dict) -> list[str]:
    text = f"{listing['title']} {listing['pitch']}"
    return [f"The pitch makes an unsupported claim: \"{match.group(0)}\". No record can promise that."
            for match in CLAIM_PATTERN.finditer(text)][:2]


def rule_red_flags(facts: dict, flags: list[str]) -> list[str]:
    found = list(flags)
    if facts["trades"] < MIN_TRADES:
        found.append(f"Only {facts['trades']} trades in the proof, too few to trust the statistics.")
    if (facts["total_return_pct"] or 0) < (facts["benchmark_return_pct"] or 0):
        found.append("The proof return is below simply buying and holding the asset.")
    if (facts["max_drawdown_pct"] or 0) > DEEP_DRAWDOWN_PCT:
        found.append(f"The proof had a deep drawdown of {facts['max_drawdown_pct']:.1f}%.")
    if facts["span_days"] < MIN_SPAN_DAYS:
        found.append(f"The proof data window is only {facts['span_days']:.0f} days.")
    if facts["reruns"] > facts["reruns_matched"]:
        found.append("At least one independent re-run did not reproduce the proof exactly.")
    if facts["track"] and facts["track"]["runs_ended_early"]:
        found.append(f"The live track died early {facts['track']['runs_ended_early']} time(s).")
    if facts["source_kind"] == "sample":
        found.append("The proof uses bundled sample data, not live market data.")
    return found


def rule_risk(facts: dict, flags: list[str]) -> str:
    count = len(rule_red_flags(facts, flags)) + len(flags)
    return "low" if count <= 1 else "medium" if count <= 3 else "high"


def rule_findings(facts: dict) -> list[str]:
    lines = [
        f"The proof returned {facts['total_return_pct']}% against {facts['benchmark_return_pct']}% for buy and hold, "
        f"with a worst drawdown of {facts['max_drawdown_pct']}% over {facts['trades']} trades.",
        f"The data window covers {facts['bars']} bars over {facts['span_days']} days.",
        f"{facts['reruns_matched']} of {facts['reruns']} independent re-runs reproduced it exactly.",
    ]
    track = facts["track"]
    if track:
        lines.append(f"The live track moved {track['equity_pct']}% over {track['seconds']} seconds across "
                     f"{track['runs_total']} run(s).")
    else:
        lines.append("There is no live track for this agent.")
    return lines


def rule_headline(risk: str, facts: dict) -> str:
    if not facts["reruns"]:
        return f"{risk.capitalize()} risk: no independent re-run of the proof yet."
    return f"{risk.capitalize()} risk: {facts['reruns_matched']} of {facts['reruns']} re-runs reproduced the proof."


def rule_report(facts: dict, flags: list[str]) -> dict:
    risk = rule_risk(facts, flags)
    return {"risk": risk, "headline": rule_headline(risk, facts), "findings": rule_findings(facts),
            "red_flags": rule_red_flags(facts, flags), "facts": facts, "by": "rules"}


def prompt_facts(listing: dict, facts: dict) -> dict:
    track = facts["track"]
    return {
        "pitch": listing["pitch"][:300],
        "proof_return_percent": facts["total_return_pct"],
        "buy_and_hold_percent": facts["benchmark_return_pct"],
        "excess_return_percent": facts["excess_return_pct"],
        "max_drawdown_percent": facts["max_drawdown_pct"],
        "sharpe": facts["sharpe"],
        "win_rate_percent": facts["win_rate_pct"],
        "trades": facts["trades"],
        "bars": facts["bars"],
        "data_days": facts["span_days"],
        "data_kind": facts["source_kind"],
        "reruns": facts["reruns"],
        "reruns_matched": facts["reruns_matched"],
        "live_track_percent": track["equity_pct"] if track else "none",
        "live_track_seconds": track["seconds"] if track else "none",
        "live_runs": track["runs_total"] if track else 0,
        "live_runs_ended_early": track["runs_ended_early"] if track else 0,
        "price_dollars": facts["price_cents"] / 100,
        "mode": facts["mode"],
        "promised_minimum_return": bps_pct(facts["min_return_bps"]),
        "free_test_drive": facts["allow_test_drive"],
    }


def build_prompt(shown: dict) -> str:
    return (
        "You are a skeptical due-diligence analyst for a marketplace of trading agents. Every agent shows a "
        "reproducible backtest proof, independent re-runs and a live paper-money track. Judge the agent from these "
        "facts only. Never invent numbers; quote only numbers that appear in the facts. Flag any pitch claim the "
        "facts do not support, such as guaranteed profits. Write for an ordinary buyer in plain words: never "
        "mention JSON field names, flags or underscores.\n"
        f"Facts: {json.dumps(shown)}\n"
        'Reply with JSON only: {"risk": "low|medium|high", "headline": "<one sentence>", '
        '"findings": ["<3 to 5 short sentences>"], "red_flags": ["<short sentences, may be empty>"]}'
    )


def clean_lines(value, minimum: int, maximum: int) -> list[str] | None:
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        return None
    if not all(isinstance(line, str) and 0 < len(line.strip()) <= MAX_LINE for line in value):
        return None
    return [" ".join(line.split()) for line in value]


def numbers_in(text: str) -> set[str]:
    return {token.rstrip("0").rstrip(".") if "." in token else token for token in NUMBER_PATTERN.findall(text)}


def invented_numbers(answer: dict, allowed_text: str) -> set[str]:
    spoken = " ".join([answer["headline"], *answer["findings"], *answer["red_flags"]])
    return numbers_in(spoken) - numbers_in(allowed_text)


def invents_numbers(answer: dict, allowed_text: str) -> bool:
    return bool(invented_numbers(answer, allowed_text))


def accept_answer(answer: dict | None, floor: str, allowed_text: str) -> dict | None:
    if not answer or answer.get("risk") not in RISKS:
        return None
    headline = answer.get("headline")
    findings = clean_lines(answer.get("findings"), 3, 5)
    red_flags = clean_lines(answer.get("red_flags", []), 0, 8)
    if not isinstance(headline, str) or not 0 < len(headline) <= MAX_HEADLINE or findings is None or red_flags is None:
        return None
    risk = max(answer["risk"], floor, key=RISKS.index)
    checked = {"headline": " ".join(headline.split()), "findings": findings, "red_flags": red_flags}
    return None if invents_numbers(checked, allowed_text) else {"risk": risk, **checked}


def retry_prompt(prompt: str, first: dict, allowed_text: str) -> str:
    try:
        bad = invented_numbers({"headline": str(first.get("headline", "")), "findings": list(first.get("findings", [])),
                                "red_flags": list(first.get("red_flags", []))}, allowed_text)
    except TypeError:
        bad = set()
    problem = f"It used numbers that are not in the facts: {', '.join(sorted(bad))}. " if bad else ""
    return (f"{prompt}\nYour previous answer was rejected. {problem}Use only numbers copied exactly from the facts, "
            "give 3 to 5 findings, and reply with the JSON object only.")


def merge_flags(red_flags: list[str], flags: list[str]) -> list[str]:
    return red_flags + [flag for flag in flags if flag not in red_flags]


def build_report(listing: dict) -> dict:
    facts = gather_facts(listing)
    flags = pitch_flags(listing)
    baseline = rule_report(facts, flags)
    shown = prompt_facts(listing, facts)
    allowed = json.dumps(shown)
    prompt = build_prompt(shown)
    first = analyst.ask(prompt)
    accepted = accept_answer(first, baseline["risk"], allowed)
    if accepted is None and first:
        accepted = accept_answer(analyst.ask(retry_prompt(prompt, first, allowed)), baseline["risk"], allowed)
    if accepted is None:
        return baseline
    accepted["red_flags"] = merge_flags(accepted["red_flags"], flags)
    return {**accepted, "facts": facts, "by": analyst.brain_name()}


def cache_key(listing: dict) -> tuple:
    view = listing_summary(listing["id"])
    track = view["track"] or {}
    return (view["reruns"]["count"], view["reruns"]["matched"], track.get("runs_total"),
            track.get("runs_ended_early"), listing["pitch"], listing["min_return_bps"])


def report(listing_id: str) -> dict:
    listing = listing_row(listing_id)
    key = cache_key(listing)
    with _cache_lock:
        stored = _cache.get(listing_id)
    if stored and stored[1] == key and time.monotonic() - stored[0] < CACHE_SECONDS:
        return stored[2]
    built = build_report(listing)
    with _cache_lock:
        _cache[listing_id] = (time.monotonic(), key, built)
    return built


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()
