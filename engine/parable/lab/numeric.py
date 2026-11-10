import hashlib
import json
import math

from .consts import DECIMALS


def round_floats(obj):
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, float):
        if not math.isfinite(obj):
            return None
        rounded = round(obj, DECIMALS)
        return 0.0 if rounded == 0 else rounded
    if isinstance(obj, dict):
        return {key: round_floats(value) for key, value in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [round_floats(value) for value in obj]
    return obj


def canonical_json(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
