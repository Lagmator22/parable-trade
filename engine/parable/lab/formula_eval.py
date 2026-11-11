import math
import operator

from . import indicators as ind
from .consts import MAX_PERIOD
from .formula_defs import FUNCS, SERIES, FormulaError

MAX_STEPS = 5_000_000
PERIOD_WEIGHT = 10
_ARITH = {"Add": operator.add, "Sub": operator.sub, "Mult": operator.mul}
_COMPARE = {
    "Lt": operator.lt, "LtE": operator.le, "Gt": operator.gt,
    "GtE": operator.ge, "Eq": operator.eq, "NotEq": operator.ne,
}


def _num(value):
    if value is None:
        return None
    return float(value)


def _finite(value):
    return value if value is not None and math.isfinite(value) else None


def _arith(name: str, a, b):
    a, b = _num(a), _num(b)
    if a is None or b is None:
        return None
    try:
        if name == "Div":
            return _finite(a / b)
        if name == "Mod":
            return _finite(a % b)
        if name == "Pow":
            return _finite(math.pow(a, b))
        return _finite(_ARITH[name](a, b))
    except (ZeroDivisionError, OverflowError, ValueError):
        return None


def _compare(name: str, a, b) -> bool:
    if a is None or b is None:
        return False
    return _COMPARE[name](a, b)


def _truth(value) -> bool:
    return value is not None and bool(value)


def _lift(fn, a, b):
    if isinstance(a, list) and isinstance(b, list):
        return [fn(x, y) for x, y in zip(a, b)]
    if isinstance(a, list):
        return [fn(x, b) for x in a]
    if isinstance(b, list):
        return [fn(a, y) for y in b]
    return fn(a, b)


def _map(fn, a):
    return [fn(x) for x in a] if isinstance(a, list) else fn(a)


def _pick(fn):
    def pick(a, b):
        a, b = _num(a), _num(b)
        return None if a is None or b is None else fn(a, b)

    return pick


class _Eval:
    def __init__(self, columns: dict, params: dict, n: int) -> None:
        self.columns = columns
        self.params = params
        self.n = n
        self.cost = 0

    def series(self, value) -> list:
        if isinstance(value, list):
            return [_num(x) for x in value] if any(isinstance(x, bool) for x in value) else value
        return [_num(value)] * self.n

    def scalar(self, node):
        if node.__class__.__name__ == "Name":
            if node.id not in self.params:
                raise FormulaError(f"unknown name '{node.id}'")
            return self.param(node.id)
        return _literal(node)

    def param(self, name: str) -> float:
        value = self.params[name]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise FormulaError(f"parameter '{name}' must be a finite number")
        return float(value)

    def period(self, node) -> int:
        value = int(round(self.scalar(node)))
        if not 1 <= value <= MAX_PERIOD:
            raise FormulaError(f"period {value} outside 1..{MAX_PERIOD}")
        return value

    def name(self, node):
        if node.id in SERIES:
            return self.columns[node.id]
        if node.id in self.params:
            return self.param(node.id)
        raise FormulaError(f"unknown name '{node.id}'")

    def call(self, node):
        fn = node.func.id
        kinds = FUNCS[fn][0]
        args = []
        self.cost += self.n
        if self.cost > MAX_STEPS:
            raise FormulaError("formula too expensive for this many bars")
        for kind, arg in zip(kinds, node.args):
            if kind == "s":
                args.append(self.series(self.node(arg)))
            elif kind == "p":
                args.append(self.period(arg))
                self.cost += self.n * (args[-1] // PERIOD_WEIGHT)
            else:
                args.append(self.scalar(arg))
        return _call(fn, args, self.columns)

    def node(self, node):
        kind = node.__class__.__name__
        if kind == "Constant":
            return float(node.value)
        if kind == "Name":
            return self.name(node)
        if kind == "BinOp":
            op = node.op.__class__.__name__
            return _lift(lambda x, y: _arith(op, x, y), self.node(node.left), self.node(node.right))
        if kind == "Compare":
            op = node.ops[0].__class__.__name__
            return _lift(lambda x, y: _compare(op, x, y), self.node(node.left), self.node(node.comparators[0]))
        if kind == "BoolOp":
            return self.boolop(node)
        if kind == "UnaryOp":
            return self.unary(node)
        if kind == "Call":
            return self.call(node)
        raise FormulaError(f"{kind} is not allowed in formulas")

    def boolop(self, node):
        is_and = node.op.__class__.__name__ == "And"
        values = [self.node(v) for v in node.values]
        combine = (lambda x, y: _truth(x) and _truth(y)) if is_and else (lambda x, y: _truth(x) or _truth(y))
        out = values[0]
        out = _map(_truth, out)
        for value in values[1:]:
            out = _lift(combine, out, value)
        return out

    def unary(self, node):
        op = node.op.__class__.__name__
        value = self.node(node.operand)
        if op == "Not":
            return _map(lambda x: not _truth(x), value)
        sign = -1.0 if op == "USub" else 1.0
        return _map(lambda x: None if x is None else sign * float(x), value)


def _literal(node) -> float:
    kind = node.__class__.__name__
    if kind == "UnaryOp":
        inner = _literal(node.operand)
        return -inner if node.op.__class__.__name__ == "USub" else inner
    return float(node.value)


def _call(fn: str, args: list, columns: dict):
    if fn == "atr":
        return ind.atr(columns["high"], columns["low"], columns["close"], args[0])
    if fn == "abs":
        return [None if x is None else abs(x) for x in args[0]]
    if fn in ("min", "max"):
        pick = _pick(min if fn == "min" else max)
        return [pick(x, y) for x, y in zip(args[0], args[1])]
    return getattr(ind, fn)(*args)


def run_formula(root, nodes: int, columns: dict, params: dict) -> list:
    missing = [name for name in SERIES if name not in columns]
    if missing:
        raise FormulaError(f"missing column '{missing[0]}'")
    n = len(columns["close"])
    if any(len(columns[name]) != n for name in SERIES):
        raise FormulaError("columns have different lengths")
    if n * nodes > MAX_STEPS:
        raise FormulaError("formula too expensive for this many bars")
    for name in params:
        if name in SERIES or name in FUNCS:
            raise FormulaError(f"parameter name '{name}' is reserved")
    evaluator = _Eval(columns, params, n)
    evaluator.cost = n * nodes
    result = evaluator.node(root)
    return list(result) if isinstance(result, list) else [result] * n


def _scalar_value(node, params: dict) -> float:
    if node.__class__.__name__ == "Name":
        if node.id not in params:
            raise FormulaError(f"unknown name '{node.id}'")
        return float(params[node.id])
    return _literal(node)


def _offset(fn: str, vals: list[float]) -> int:
    ints = [max(1, int(round(v))) for v in vals]
    if fn in ("sma", "ema", "bb_upper", "bb_lower", "atr", "stddev", "highest", "lowest"):
        return ints[0] - 1
    if fn in ("rsi", "roc", "prev"):
        return ints[0]
    if fn == "macd":
        return max(ints[0], ints[1]) - 1
    if fn == "macd_signal":
        return max(ints[0], ints[1]) + ints[2] - 2
    return 0


def warm_up(node, params: dict) -> int:
    kind = node.__class__.__name__
    if kind in ("Constant", "Name"):
        return 0
    children = {
        "BinOp": lambda: [node.left, node.right],
        "Compare": lambda: [node.left, node.comparators[0]],
        "BoolOp": lambda: list(node.values),
        "UnaryOp": lambda: [node.operand],
    }
    if kind in children:
        return max(warm_up(c, params) for c in children[kind]())
    fn = node.func.id
    kinds = FUNCS[fn][0]
    series = [warm_up(a, params) for k, a in zip(kinds, node.args) if k == "s"]
    scalars = [_scalar_value(a, params) for k, a in zip(kinds, node.args) if k == "p"]
    base = max(series) if series else 0
    if fn == "prev" and not scalars:
        scalars = [1.0]
    if fn in ("cross_above", "cross_below"):
        return base + 1
    return base + _offset(fn, scalars)


def static_cost(node, params: dict, bars: int) -> int:
    kind = node.__class__.__name__
    if kind in ("Constant", "Name"):
        return bars
    if kind == "BinOp":
        children = [node.left, node.right]
    elif kind == "Compare":
        children = [node.left, node.comparators[0]]
    elif kind == "BoolOp":
        children = list(node.values)
    elif kind == "UnaryOp":
        children = [node.operand]
    else:
        total = bars
        for arg_kind, arg in zip(FUNCS[node.func.id][0], node.args):
            if arg_kind == "s":
                total += static_cost(arg, params, bars)
            elif arg_kind == "p":
                total += bars * (max(1, int(round(_scalar_value(arg, params)))) // PERIOD_WEIGHT)
        return total
    return bars + sum(static_cost(child, params, bars) for child in children)
