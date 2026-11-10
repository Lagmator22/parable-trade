from pydantic import BaseModel

from parable.errors import LabError
from parable.lab.describe import CompileResult, describe_spec
from parable.lab.formula import parse, period_params
from parable.lab.spec import SpecError, validate_spec
from parable.lab.templates import TEMPLATES, template_spec

SPEED = {"fast": 0.5, "medium": 1.0, "slow": 2.0}
RISK = {"tight": 2.0, "normal": 5.0, "wide": 10.0}
SIZE = {"small": 25.0, "half": 50.0, "full": 100.0}
DEFAULTS = {"speed": "medium", "risk": "normal", "size": "full"}
SPEED_LABELS = {"fast": "Fast (react quickly)", "medium": "Medium", "slow": "Slow (wait for confirmation)"}
RISK_LABELS = {"tight": "Tight (2% stop)", "normal": "Normal (5% stop)", "wide": "Wide (10% stop)"}
SIZE_LABELS = {"small": "Small (25% of cash)", "half": "Half (50% of cash)", "full": "Full (100% of cash)"}


class Option(BaseModel):
    id: str
    label: str


class Question(BaseModel):
    id: str
    text: str
    options: list[Option]


def questions() -> list[Question]:
    return [
        Question(id="family", text="What kind of move should the strategy look for?",
                 options=[Option(id=k, label=t["label"]) for k, t in TEMPLATES.items()]),
        Question(id="speed", text="How quickly should it react?",
                 options=[Option(id=k, label=v) for k, v in SPEED_LABELS.items()]),
        Question(id="risk", text="How much loss can a single trade take before it exits?",
                 options=[Option(id=k, label=v) for k, v in RISK_LABELS.items()]),
        Question(id="size", text="How much of the cash should each trade use?",
                 options=[Option(id=k, label=v) for k, v in SIZE_LABELS.items()]),
    ]


def jev_questions() -> dict:
    return {q.id: {"instructions": q.text, "options": [o.id for o in q.options]} for q in questions()}


def check_answers(answers: dict) -> dict[str, str]:
    valid = {q.id: {o.id for o in q.options} for q in questions()}
    chosen = {**DEFAULTS, **{k: v for k, v in (answers or {}).items() if k in valid}}
    if "family" not in chosen:
        raise LabError(400, "bad_request", "pick a strategy family")
    for qid, option in chosen.items():
        if option not in valid[qid]:
            raise LabError(400, "bad_request", f"{option!r} is not an option for {qid}")
    return chosen


def scale_periods(spec, factor: float):
    names = set()
    for text in (spec.entry, spec.exit):
        if text.strip():
            names |= period_params(parse(text))
    params = {}
    for name, p in spec.params.items():
        if name in names:
            scaled = min(p.max, max(p.min, 1, round(p.value * factor)))
            params[name] = p.model_copy(update={"value": float(scaled)})
        else:
            params[name] = p
    return spec.model_copy(update={"params": params})


def build_from_answers(answers: dict[str, str], symbol: str, interval: str, *,
                       built_by: str | None = None) -> CompileResult:
    chosen = check_answers(answers)
    spec = scale_periods(template_spec(chosen["family"], symbol, interval), SPEED[chosen["speed"]])
    label = TEMPLATES[chosen["family"]]["label"]
    spec = spec.model_copy(update={
        "name": label, "built_by": built_by or "questionnaire", "stop_loss_pct": RISK[chosen["risk"]],
        "trailing_stop_pct": 0.0, "size_pct": SIZE[chosen["size"]],
        "summary": f"{label}, {chosen['speed']} pace, {chosen['risk']} stop, {chosen['size']} position size."})
    try:
        validate_spec(spec)
    except SpecError as err:
        raise LabError(502, "bad_output", f"could not build that strategy: {err.errors[0]}") from None
    return CompileResult(spec=spec, summary=spec.summary, rules=describe_spec(spec), built_by=spec.built_by, attempts=1)
