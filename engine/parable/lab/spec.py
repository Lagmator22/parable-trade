import json
import math

from pydantic import ValidationError

from ..db import one
from ..errors import LabError
from ..models import StrategySpec
from .consts import INTERVALS, MAX_PARAM_VALUES, MAX_PARAMS, MAX_PERIOD, MAX_SPEC_BYTES
from .formula import FormulaError, dry_run, parse, period_params, referenced_params, warmup
from .formula_defs import NAME_RE, RESERVED
from .numeric import canonical_json, round_floats, sha256_hex

HASH_KEYS = (
    "symbol", "interval", "params", "entry", "exit", "size_pct",
    "stop_loss_pct", "take_profit_pct", "trailing_stop_pct", "fee_bps", "slippage_bps",
)


class SpecError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


def canonical_spec(spec: StrategySpec) -> dict:
    data = spec.model_dump()
    data["entry"] = spec.entry.strip()
    data["exit"] = spec.exit.strip()
    return round_floats(data)


def spec_hash(spec: StrategySpec) -> str:
    data = canonical_spec(spec)
    return sha256_hex(canonical_json({key: data[key] for key in HASH_KEYS}))


def param_count(low: float, high: float, step: float) -> int:
    if not all(math.isfinite(x) for x in (low, high, step)) or step <= 0 or high < low:
        return 0
    return int(math.floor((high - low) / step + 1e-9)) + 1


def _param_errors(spec: StrategySpec, periods: set[str]) -> list[str]:
    errors = []
    if len(spec.params) > MAX_PARAMS:
        errors.append(f"params: at most {MAX_PARAMS} allowed")
    for name, p in spec.params.items():
        if not NAME_RE.match(name) or name in RESERVED:
            errors.append(f"params.{name}: invalid or reserved name")
            continue
        if not all(math.isfinite(x) for x in (p.value, p.min, p.max, p.step)):
            errors.append(f"params.{name}: values must be finite")
        elif not p.min <= p.value <= p.max:
            errors.append(f"params.{name}: need min <= value <= max")
        elif param_count(p.min, p.max, p.step) > MAX_PARAM_VALUES:
            errors.append(f"params.{name}: more than {MAX_PARAM_VALUES} values between min and max")
        if name in periods and not _period_ok(p):
            errors.append(f"params.{name}: used as a period, needs whole value and range within 1..{MAX_PERIOD}")
    return errors


def _period_ok(p) -> bool:
    return p.value == int(p.value) and p.min >= 1 and p.max <= MAX_PERIOD


def _formula_errors(spec: StrategySpec) -> tuple[list[str], set[str]]:
    errors, periods = [], set()
    for label, text in (("entry", spec.entry), ("exit", spec.exit)):
        if label == "exit" and not text.strip():
            continue
        try:
            expr = parse(text)
        except FormulaError as exc:
            errors.append(f"{label}: {exc}")
            continue
        periods |= period_params(expr)
        for name in sorted(referenced_params(expr) - set(spec.params)):
            errors.append(f"{label}: unknown name '{name}'")
    return errors, periods


def validate_spec(spec: StrategySpec) -> None:
    errors: list[str] = []
    if spec.interval not in INTERVALS:
        errors.append(f"interval: must be one of {', '.join(INTERVALS)}")
    if not spec.symbol.strip():
        errors.append("symbol: required")
    formula_errors, periods = _formula_errors(spec)
    errors += formula_errors + _param_errors(spec, periods)
    if len(canonical_json(canonical_spec(spec)).encode()) > MAX_SPEC_BYTES:
        errors.append(f"spec larger than {MAX_SPEC_BYTES} bytes")
    if not errors:
        try:
            dry_run(spec)
        except FormulaError as exc:
            errors.append(f"dry run: {exc}")
    if errors:
        raise SpecError(errors)


def _pydantic_errors(exc: ValidationError) -> list[str]:
    return [f"{'.'.join(str(x) for x in e['loc'])}: {e['msg']}" for e in exc.errors()]


def parse_spec(raw: dict | str) -> StrategySpec:
    if isinstance(raw, str):
        if len(raw.encode()) > MAX_SPEC_BYTES * 2:
            raise SpecError(["spec too large"])
        try:
            raw = json.loads(raw)
        except (ValueError, RecursionError):
            raise SpecError(["spec is not valid JSON"]) from None
    if not isinstance(raw, dict):
        raise SpecError(["spec must be a JSON object"])
    try:
        spec = StrategySpec.model_validate(raw)
    except ValidationError as exc:
        raise SpecError(_pydantic_errors(exc)) from None
    spec = spec.model_copy(update={"entry": spec.entry.strip(), "exit": spec.exit.strip()})
    validate_spec(spec)
    return spec


def resolve_params(spec: StrategySpec, overrides: dict | None = None) -> dict[str, float]:
    values = {name: float(p.value) for name, p in spec.params.items()}
    for name, value in (overrides or {}).items():
        if name not in values:
            raise SpecError([f"params.{name}: unknown parameter"])
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise SpecError([f"params.{name}: must be a finite number"])
        values[name] = float(value)
    return values


def with_params(spec: StrategySpec, overrides: dict | None) -> StrategySpec:
    if not overrides:
        return spec
    values = resolve_params(spec, overrides)
    params = {name: p.model_copy(update={"value": values[name]}) for name, p in spec.params.items()}
    return spec.model_copy(update={"params": params})


def warmup_bars(spec: StrategySpec, params: dict | None = None) -> int:
    values = resolve_params(spec, params)
    texts = [t for t in (spec.entry, spec.exit) if t.strip()]
    return max((warmup(parse(t), values) for t in texts), default=0)


def required_bars(spec: StrategySpec) -> int:
    return max(300, 3 * warmup_bars(spec))


def load_spec(version_id: str) -> StrategySpec:
    row = one("SELECT spec_json FROM agent_versions WHERE id = ?", (version_id,))
    if row is None:
        raise LabError(404, "not_found", "version not found")
    return StrategySpec.model_validate_json(row["spec_json"])
