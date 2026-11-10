import json
import re
import threading
import time

from parable import analyst, referee
from parable.listings import listing_row

CACHE_SECONDS = 60
THIN_RECORD_RUNS = 3
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
    record = referee.seller_record(listing["seller_id"])
    probations = record["probation_passed"] + record["probation_failed"]
    return {
        **record,
        "thin_record": record["ended"] < THIN_RECORD_RUNS,
        "probation_pass_rate": record["probation_passed"] / probations if probations else None,
        "price_cents": listing["price_cents"],
        "probation_s": listing["probation_s"],
        "min_return_bps": listing["min_return_bps"],
        "max_loss_bps": json.loads(listing["rules_json"])["max_loss_bps"],
        "strategy": json.loads(listing["rules_json"])["strategy"],
    }


def pitch_flags(listing: dict) -> list[str]:
    text = f"{listing['title']} {listing['pitch']}"
    return [f"The pitch makes an unsupported claim: \"{match.group(0)}\". No record can promise that."
            for match in CLAIM_PATTERN.finditer(text)][:2]


def rule_risk(facts: dict, flags: list[str]) -> str:
    points = 2 * len(flags) + (2 if facts["thin_record"] else 0)
    if facts["ended"]:
        points += 4 if facts["survival_rate"] < 0.5 else 1 if facts["survival_rate"] < 0.8 else 0
        points += 1 if facts["worst_return_bps"] <= -facts["max_loss_bps"] else 0
    return "low" if points <= 1 else "medium" if points <= 3 else "high"


def rule_findings(facts: dict) -> list[str]:
    if not facts["ended"]:
        return ["This seller has no finished runs yet, so there is no track record to judge.",
                f"Payment is held for {facts['probation_s'] // 60} minutes and only captured if the bot survives."]
    lines = [
        f"{facts['survived']} of {facts['ended']} finished runs survived to the end ({pct(facts['survival_rate'])}).",
        f"Average return {bps_pct(facts['avg_return_bps'])}, worst {bps_pct(facts['worst_return_bps'])}, "
        f"best {bps_pct(facts['best_return_bps'])}.",
        f"{facts['total_trades']} trades were made and {facts['total_refusals']} were refused by the referee.",
    ]
    if facts["probation_pass_rate"] is not None:
        lines.append(f"{facts['probation_passed']} of {facts['probation_passed'] + facts['probation_failed']} "
                     "buyer probations passed.")
    return lines


def rule_red_flags(facts: dict, flags: list[str]) -> list[str]:
    found = list(flags)
    if facts["thin_record"]:
        found.append(f"Thin record: fewer than {THIN_RECORD_RUNS} finished runs.")
    if facts["loss_limit"]:
        found.append(f"{facts['loss_limit']} run(s) died to the loss limit.")
    if facts["min_return_bps"] < 0:
        found.append(f"The promised minimum return is {bps_pct(facts['min_return_bps'])}, so a losing bot can still pass.")
    return found


def rule_headline(risk: str, facts: dict) -> str:
    if not facts["ended"]:
        return "Unproven: no finished runs on record."
    return f"{risk.capitalize()} risk: {facts['survived']} of {facts['ended']} runs survived."


def rule_report(facts: dict, flags: list[str]) -> dict:
    risk = rule_risk(facts, flags)
    return {"risk": risk, "headline": rule_headline(risk, facts), "findings": rule_findings(facts),
            "red_flags": rule_red_flags(facts, flags), "facts": facts, "by": "rules"}


def prompt_facts(listing: dict, facts: dict) -> dict:
    rate = facts["probation_pass_rate"]
    return {
        "pitch": listing["pitch"][:300],
        "strategy": facts["strategy"],
        "finished_runs": facts["ended"],
        "survived_runs": facts["survived"],
        "survival_rate": pct(facts["survival_rate"]),
        "died_to_loss_limit": facts["loss_limit"],
        "average_return": bps_pct(facts["avg_return_bps"]),
        "worst_return": bps_pct(facts["worst_return_bps"]),
        "best_return": bps_pct(facts["best_return_bps"]),
        "trades": facts["total_trades"],
        "refused_trades": facts["total_refusals"],
        "buyer_probations_passed": facts["probation_passed"],
        "buyer_probations_failed": facts["probation_failed"],
        "probation_pass_rate": pct(rate) if rate is not None else "n/a",
        "loss_limit": f"{facts['max_loss_bps'] / 100:.2f}%",
        "probation_minutes": facts["probation_s"] // 60,
        "price_dollars": facts["price_cents"] / 100,
        "promised_minimum_return": bps_pct(facts["min_return_bps"]),
        "record_is_thin": facts["thin_record"],
    }


def build_prompt(shown: dict) -> str:
    return (
        "You are a skeptical due-diligence analyst for a marketplace where buyers pay for AI trading bots only "
        "if the bot survives a paper-money probation. Judge the seller from these facts only. Never invent "
        "numbers; quote only numbers that appear in the facts. Flag any pitch claim the facts do not support, "
        "such as guaranteed profits.\n"
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


def invents_numbers(answer: dict, allowed_text: str) -> bool:
    spoken = " ".join([answer["headline"], *answer["findings"], *answer["red_flags"]])
    return not numbers_in(spoken) <= numbers_in(allowed_text)


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


def merge_flags(red_flags: list[str], flags: list[str]) -> list[str]:
    return red_flags + [flag for flag in flags if flag not in red_flags]


def build_report(listing: dict) -> dict:
    facts = gather_facts(listing)
    flags = pitch_flags(listing)
    baseline = rule_report(facts, flags)
    shown = prompt_facts(listing, facts)
    allowed = json.dumps(shown)
    accepted = accept_answer(analyst.ask(build_prompt(shown)), baseline["risk"], allowed)
    if accepted is None:
        return baseline
    accepted["red_flags"] = merge_flags(accepted["red_flags"], flags)
    return {**accepted, "facts": facts, "by": analyst.brain_name()}


def cache_key(listing: dict) -> tuple:
    record = referee.seller_record(listing["seller_id"])
    return (record["runs"], record["ended"], listing["pitch"], listing["min_return_bps"])


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
