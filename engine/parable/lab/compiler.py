import json
import math

from parable.errors import LabError
from parable.lab import llm
from parable.lab.consts import MAX_PARAM_VALUES, MAX_STEPS_CHARS
from parable.lab.describe import CompileResult, RuleChip, describe_spec
from parable.lab.formula import FORMULA_REFERENCE
from parable.lab.llm import AiAuth
from parable.lab.questionnaire import Question, build_from_answers, jev_questions, questions
from parable.lab.spec import SpecError, parse_spec
from parable.lab.templates import list_templates
from parable.models import StrategySpec

__all__ = ["RuleChip", "CompileResult", "Question", "describe_spec", "questions", "build_from_answers",
           "compile_steps", "jev_build", "ideas", "built_by_for"]

SYSTEM = "You turn plain-language trading steps into one strategy spec. Reply with a single JSON object and nothing else."
KEYS = ("name (max 60 chars), summary (max 300 chars), params (object: name -> {value, min, max, step}), "
        "entry (formula), exit (formula, may be empty), size_pct (1-100), stop_loss_pct (0-50), "
        "take_profit_pct (0-1000), trailing_stop_pct (0-50), fee_bps (0-200), slippage_bps (0-200)")
SPEC_KEYS = ("name", "summary", "params", "entry", "exit", "size_pct", "stop_loss_pct", "take_profit_pct",
             "trailing_stop_pct", "fee_bps", "slippage_bps")


def built_by_for(auth: AiAuth) -> str:
    return auth.model if auth.provider == "platform" else f"{auth.provider}:{auth.model}"


def clean_steps(steps: str) -> str:
    text = (steps or "").strip()
    if not text:
        raise LabError(400, "bad_request", "describe the strategy steps first")
    if len(text) > MAX_STEPS_CHARS:
        raise LabError(413, "too_large", f"keep the steps under {MAX_STEPS_CHARS} characters")
    return text


def build_prompt(steps: str, symbol: str, interval: str, base: StrategySpec | None, count: int | None = None) -> str:
    templates = "\n".join(f"- {t['id']}: {t['label']}, {t['blurb']}" for t in list_templates())
    parts = [FORMULA_REFERENCE, "TEMPLATE IDEAS (for inspiration only)\n" + templates,
             f"The strategy trades {symbol} on {interval} candles, long only."]
    if base is not None:
        parts.append("CURRENT STRATEGY (change it only as the steps ask)\n"
                     + json.dumps({k: v for k, v in base.model_dump().items() if k in SPEC_KEYS}))
    parts.append(f"STEPS FROM THE USER\n{steps}")
    if count:
        parts.append(f"Return JSON {{\"variants\": [...]}} with {count} different specs, each with keys: {KEYS}.")
    else:
        parts.append(f"Return one JSON object with keys: {KEYS}.")
    return "\n\n".join(parts)


def widen_step(param) -> None:
    if not isinstance(param, dict):
        return
    try:
        low, high = float(param["min"]), float(param["max"])
    except (KeyError, TypeError, ValueError):
        return
    if not (math.isfinite(low) and math.isfinite(high)) or high <= low:
        return
    try:
        step = float(param.get("step", 1.0))
    except (TypeError, ValueError):
        step = 1.0
    need = (high - low) / (MAX_PARAM_VALUES - 1)
    if not math.isfinite(step) or step <= 0 or (high - low) / step + 1 > MAX_PARAM_VALUES:
        magnitude = 10 ** math.floor(math.log10(need))
        param["step"] = next((m * magnitude for m in (1, 2, 2.5, 5, 10) if m * magnitude >= need * 1.0001), need)


def repair_params(data: dict) -> None:
    params = data.get("params")
    if isinstance(params, dict):
        data["params"] = {k: dict(v) if isinstance(v, dict) else v for k, v in params.items()}
        for param in data["params"].values():
            widen_step(param)


def to_spec(raw, symbol: str, interval: str, built_by: str) -> StrategySpec:
    if not isinstance(raw, dict):
        raise SpecError(["the answer was not a JSON object"])
    data = {k: raw[k] for k in SPEC_KEYS if k in raw}
    data["name"] = str(data.get("name") or "Untitled")[:60]
    data["summary"] = str(data.get("summary") or "")[:300]
    data.update(symbol=symbol, interval=interval, built_by=built_by)
    repair_params(data)
    return parse_spec(data)


def result_of(spec: StrategySpec, attempts: int) -> CompileResult:
    return CompileResult(spec=spec, summary=spec.summary, rules=describe_spec(spec), built_by=spec.built_by,
                         attempts=attempts)


def jev_build(steps: str, symbol: str, interval: str, auth: AiAuth) -> CompileResult:
    steps = clean_steps(steps)
    model = auth.model.removeprefix("jev:")
    situation = f"A person describes a trading strategy for {symbol} on {interval} candles: {steps}"
    answers = llm.jev_choices(model, situation, jev_questions())
    return build_from_answers(answers, symbol, interval, built_by=f"jev:{model}")


def compile_steps(steps: str, symbol: str, interval: str, auth: AiAuth, *,
                  base: StrategySpec | None = None) -> CompileResult:
    steps = clean_steps(steps)
    if auth.provider == "platform" and auth.model.startswith("jev:"):
        return jev_build(steps, symbol, interval, auth)
    built_by = built_by_for(auth)
    prompt = build_prompt(steps, symbol, interval, base)
    problem = ""
    for attempt in (1, 2):
        try:
            raw = llm.chat_json(auth, prompt, system=SYSTEM)
            return result_of(to_spec(raw, symbol, interval, built_by), attempt)
        except SpecError as err:
            problem = "; ".join(err.errors[:6])
            previous = json.dumps(raw)[:3000]
        except LabError as err:
            if err.code != "bad_output":
                raise
            problem, previous = err.detail, ""
        prompt = (build_prompt(steps, symbol, interval, base) + "\n\nYour previous answer was rejected."
                  + (f"\nPrevious answer: {previous}" if previous else "")
                  + f"\nProblems: {problem}\nFix every problem and return the corrected JSON object only.")
    raise LabError(502, "bad_output", f"the model could not produce a valid strategy: {problem}")


def ideas(base: StrategySpec, steps: str, auth: AiAuth, n: int = 3) -> list[CompileResult]:
    steps = clean_steps(steps)
    if auth.provider == "platform" and auth.model.startswith("jev:"):
        raise LabError(400, "bad_request", "idea variants need a chat model, pick another model")
    n = max(1, min(int(n), 5))
    raw = llm.chat_json(auth, build_prompt(steps, base.symbol, base.interval, base, n), system=SYSTEM)
    variants = raw.get("variants") if isinstance(raw, dict) else None
    found: list[CompileResult] = []
    for item in variants if isinstance(variants, list) else []:
        try:
            found.append(result_of(to_spec(item, base.symbol, base.interval, built_by_for(auth)), 1))
        except SpecError:
            continue
    if not found:
        raise LabError(502, "bad_output", "the model did not return any valid variants")
    return found[:n]
