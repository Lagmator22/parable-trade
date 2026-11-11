import ast
import math
from dataclasses import dataclass

from ..models import StrategySpec
from .consts import MAX_AST_DEPTH, MAX_BARS, MAX_AST_NODES, MAX_FORMULA_LEN, MAX_PERIOD, MAX_POW
from .formula_defs import FORMULA_REFERENCE, FUNCS, MAX_CONSTANT, NAME_RE, RESERVED, SERIES, FormulaError
from .formula_eval import MAX_STEPS, run_formula, static_cost, warm_up

__all__ = [
    "FORMULA_REFERENCE", "FormulaError", "Expr", "parse", "referenced_params",
    "period_params", "warmup", "evaluate", "dry_run", "synthetic_columns",
]

_BIN = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod, ast.Pow)
_CMP = (ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.Eq, ast.NotEq)
_UNARY = (ast.USub, ast.UAdd, ast.Not)
_BOOL = (ast.And, ast.Or)


@dataclass(frozen=True)
class Expr:
    text: str
    root: ast.expr
    nodes: int


def _number(node: ast.AST) -> float | None:
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        inner = _number(node.operand)
        return None if inner is None else (-inner if isinstance(node.op, ast.USub) else inner)
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        value = node.value
        if abs(value) > MAX_CONSTANT or (isinstance(value, float) and not math.isfinite(value)):
            raise FormulaError("constant out of range")
        return float(value)
    return None


def _check_name(node: ast.Name) -> None:
    if not isinstance(node.ctx, ast.Load):
        raise FormulaError("names may only be read")
    if node.id in FUNCS:
        raise FormulaError(f"function '{node.id}' must be called with arguments")
    if node.id not in SERIES and (node.id.startswith("__") or not NAME_RE.match(node.id)):
        raise FormulaError(f"invalid name '{node.id}'")


def _check_scalar_arg(kind: str, node: ast.expr, fn: str) -> None:
    if isinstance(node, ast.Name):
        _check_name(node)
        if node.id in SERIES:
            raise FormulaError(f"{fn}: period/multiplier must be a number or parameter, not a series")
        return
    value = _number(node)
    if value is None:
        raise FormulaError(f"{fn}: period/multiplier must be a number literal or a parameter name")
    if kind == "p" and (value != int(value) or not 1 <= value <= MAX_PERIOD):
        raise FormulaError(f"{fn}: period must be an integer 1..{MAX_PERIOD}")


def _check_call(node: ast.Call, depth: int) -> None:
    if not isinstance(node.func, ast.Name):
        raise FormulaError("only plain function names can be called")
    if node.keywords:
        raise FormulaError("keyword arguments are not allowed")
    name = node.func.id
    if name not in FUNCS:
        raise FormulaError(f"unknown function '{name}'")
    kinds, minimum = FUNCS[name]
    if not minimum <= len(node.args) <= len(kinds):
        raise FormulaError(f"{name} takes {minimum}..{len(kinds)} arguments")
    for kind, arg in zip(kinds, node.args):
        if kind == "s":
            _check(arg, depth + 1)
        else:
            _check_scalar_arg(kind, arg, name)


def _check_pow(node: ast.BinOp) -> None:
    exponent = _number(node.right)
    if exponent is None or abs(exponent) > MAX_POW:
        raise FormulaError(f"exponent must be a numeric literal with abs <= {MAX_POW}")


def _check(node: ast.AST, depth: int) -> None:
    if depth > MAX_AST_DEPTH:
        raise FormulaError(f"formula nesting deeper than {MAX_AST_DEPTH}")
    if isinstance(node, ast.BoolOp):
        if not isinstance(node.op, _BOOL):
            raise FormulaError("unsupported boolean operator")
        for value in node.values:
            _check(value, depth + 1)
    elif isinstance(node, ast.UnaryOp):
        if not isinstance(node.op, _UNARY):
            raise FormulaError("unsupported unary operator")
        _check(node.operand, depth + 1)
    elif isinstance(node, ast.BinOp):
        if not isinstance(node.op, _BIN):
            raise FormulaError("unsupported operator")
        if isinstance(node.op, ast.Pow):
            _check_pow(node)
        _check(node.left, depth + 1)
        _check(node.right, depth + 1)
    elif isinstance(node, ast.Compare):
        if len(node.ops) != 1:
            raise FormulaError("chained comparisons are not allowed")
        if not isinstance(node.ops[0], _CMP):
            raise FormulaError("unsupported comparison operator")
        _check(node.left, depth + 1)
        _check(node.comparators[0], depth + 1)
    elif isinstance(node, ast.Call):
        _check_call(node, depth)
    elif isinstance(node, ast.Name):
        _check_name(node)
    elif isinstance(node, ast.Constant):
        if _number(node) is None:
            raise FormulaError(f"{type(node.value).__name__} constants are not allowed")
    else:
        raise FormulaError(f"{type(node).__name__} is not allowed in formulas")


def parse(text: str) -> Expr:
    if not isinstance(text, str):
        raise FormulaError("formula must be text")
    stripped = text.strip()
    if not stripped:
        raise FormulaError("formula is empty")
    if len(stripped) > MAX_FORMULA_LEN:
        raise FormulaError(f"formula longer than {MAX_FORMULA_LEN} characters")
    try:
        tree = ast.parse(stripped, mode="eval")
    except (SyntaxError, ValueError, RecursionError, MemoryError) as exc:
        raise FormulaError(f"syntax error: {str(exc).splitlines()[0][:80]}") from None
    nodes = sum(1 for n in ast.walk(tree.body) if isinstance(n, ast.expr))
    if nodes > MAX_AST_NODES:
        raise FormulaError(f"formula has more than {MAX_AST_NODES} nodes")
    _check(tree.body, 1)
    return Expr(stripped, tree.body, nodes)


def _names(expr: Expr) -> list[ast.Name]:
    callees = {id(n.func) for n in ast.walk(expr.root) if isinstance(n, ast.Call)}
    return [n for n in ast.walk(expr.root) if isinstance(n, ast.Name) and id(n) not in callees]


def referenced_params(expr: Expr) -> set[str]:
    return {n.id for n in _names(expr) if n.id not in SERIES}


def period_params(expr: Expr) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(expr.root):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            kinds = FUNCS[node.func.id][0]
            for kind, arg in zip(kinds, node.args):
                if kind == "p" and isinstance(arg, ast.Name):
                    found.add(arg.id)
    return found


def warmup(expr: Expr, params: dict[str, float]) -> int:
    return warm_up(expr.root, params)


def evaluate(expr: Expr, columns: dict[str, list[float]], params: dict[str, float]) -> list:
    return run_formula(expr.root, expr.nodes, columns, params)


def synthetic_columns(n: int = 300) -> dict[str, list[float]]:
    close = [100.0 + 10.0 * math.sin(i / 9.0) + 3.0 * math.sin(i / 3.1) + 0.05 * i for i in range(n)]
    opens = [close[0]] + close[:-1]
    high = [max(o, c) + 0.5 + 0.2 * math.sin(i) ** 2 for i, (o, c) in enumerate(zip(opens, close))]
    low = [min(o, c) - 0.5 - 0.2 * math.cos(i) ** 2 for i, (o, c) in enumerate(zip(opens, close))]
    volume = [1000.0 + 100.0 * (1.0 + math.sin(i * 0.7)) for i in range(n)]
    return {"open": opens, "high": high, "low": low, "close": close, "volume": volume}


def dry_run(spec: StrategySpec) -> None:
    columns = synthetic_columns(300)
    params = {name: p.value for name, p in spec.params.items()}
    for text in (spec.entry, spec.exit):
        if text.strip():
            evaluate(parse(text), columns, params)


def check_cost(spec: StrategySpec) -> None:
    total = 0
    for text in (spec.entry, spec.exit):
        if not text.strip():
            continue
        expr = parse(text)
        periods = period_params(expr)
        values = {name: float(p.max if name in periods else p.value) for name, p in spec.params.items()}
        total += static_cost(expr.root, values, MAX_BARS)
    if total > MAX_STEPS:
        raise FormulaError("formula too expensive: use fewer or shorter indicators")
