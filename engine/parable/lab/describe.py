import ast
from typing import Literal

from pydantic import BaseModel

from parable.lab.formula import parse
from parable.models import StrategySpec

COMPARE_WORDS = {ast.Lt: "is below", ast.LtE: "is at or below", ast.Gt: "is above", ast.GtE: "is at or above",
                 ast.Eq: "equals", ast.NotEq: "differs from"}
BINOP_SIGNS = {ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.Div: "/", ast.Mod: "%", ast.Pow: "^"}
SERIES_WORDS = {"close": "price", "open": "the open", "high": "the high", "low": "the low", "volume": "volume"}


class RuleChip(BaseModel):
    kind: Literal["entry", "exit", "risk", "size"]
    text: str


class CompileResult(BaseModel):
    spec: StrategySpec
    summary: str
    rules: list[RuleChip]
    built_by: str
    attempts: int


def num(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:g}"


def wrap(node, params: dict) -> str:
    text = words(node, params)
    return f"({text})" if isinstance(node, (ast.BinOp, ast.BoolOp, ast.Compare)) else text


def src_phrase(node, params: dict) -> str:
    return "" if isinstance(node, ast.Name) and node.id == "close" else f" of {words(node, params)}"


def call_words(name: str, args: list, params: dict) -> str:
    a = [words(x, params) for x in args]
    plain = {"sma": "SMA", "ema": "EMA", "rsi": "RSI", "roc": "ROC", "stddev": "StdDev"}
    if name == "cross_above":
        return f"{a[0]} crosses above {a[1]}"
    if name == "cross_below":
        return f"{a[0]} crosses below {a[1]}"
    if name in plain:
        return f"{plain[name]}({a[1]}){src_phrase(args[0], params)}"
    if name == "macd":
        return f"MACD({a[1]}, {a[2]})"
    if name == "macd_signal":
        return f"MACD signal({a[1]}, {a[2]}, {a[3]})"
    if name in ("bb_upper", "bb_lower"):
        side = "upper" if name == "bb_upper" else "lower"
        return f"{side} Bollinger band({a[1]}, {a[2]})"
    if name == "atr":
        return f"ATR({a[0]})"
    if name in ("highest", "lowest"):
        return f"{name} {a[0]} of the last {a[1]} bars"
    if name == "prev":
        lag = a[1] if len(a) > 1 else "1"
        return f"previous {a[0]}" if lag == "1" else f"{a[0]} {lag} bars ago"
    return f"{name}({', '.join(a)})"


def words(node, params: dict) -> str:
    if isinstance(node, ast.Constant):
        return num(node.value)
    if isinstance(node, ast.Name):
        if node.id in params:
            return num(params[node.id])
        return SERIES_WORDS.get(node.id, node.id)
    if isinstance(node, ast.Call):
        return call_words(node.func.id, node.args, params)
    if isinstance(node, ast.Compare):
        return f"{wrap(node.left, params)} {COMPARE_WORDS[type(node.ops[0])]} {wrap(node.comparators[0], params)}"
    if isinstance(node, ast.BoolOp):
        joiner = " and " if isinstance(node.op, ast.And) else " or "
        return joiner.join(wrap(v, params) if isinstance(v, ast.BoolOp) else words(v, params) for v in node.values)
    if isinstance(node, ast.BinOp):
        return f"{wrap(node.left, params)} {BINOP_SIGNS[type(node.op)]} {wrap(node.right, params)}"
    if isinstance(node, ast.UnaryOp):
        if isinstance(node.op, ast.Not):
            return f"not ({words(node.operand, params)})"
        return ("-" if isinstance(node.op, ast.USub) else "") + wrap(node.operand, params)
    return "?"


def describe_formula(text: str, params: dict) -> str:
    return words(parse(text).root, params)


def describe_spec(spec: StrategySpec) -> list[RuleChip]:
    values = {name: p.value for name, p in spec.params.items()}
    chips = [RuleChip(kind="entry", text=f"Buy when {describe_formula(spec.entry, values)}")]
    if spec.exit.strip():
        chips.append(RuleChip(kind="exit", text=f"Sell when {describe_formula(spec.exit, values)}"))
    if spec.stop_loss_pct:
        chips.append(RuleChip(kind="risk", text=f"Stop loss {num(spec.stop_loss_pct)}%"))
    if spec.take_profit_pct:
        chips.append(RuleChip(kind="risk", text=f"Take profit {num(spec.take_profit_pct)}%"))
    if spec.trailing_stop_pct:
        chips.append(RuleChip(kind="risk", text=f"Trailing stop {num(spec.trailing_stop_pct)}%"))
    chips.append(RuleChip(kind="size", text=f"Use {num(spec.size_pct)}% of cash"))
    chips.append(RuleChip(kind="risk",
                          text=f"Fees {spec.fee_bps / 100:.2f}% + {spec.slippage_bps / 100:.2f}% slippage per side"))
    return chips
