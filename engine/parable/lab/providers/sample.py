import csv
import json
from functools import lru_cache
from pathlib import Path

from parable.lab.markets import MarketDataError, Quote, SymbolInfo
from parable.lab.providers.base import clip

SAMPLES = Path(__file__).resolve().parent.parent / "samples"


@lru_cache(maxsize=1)
def manifest() -> dict[str, dict]:
    path = SAMPLES / "SOURCES.json"
    if not path.exists():
        return {}
    found = json.loads(path.read_text())
    return {name: meta for name, meta in found.items() if (SAMPLES / name).exists()}


@lru_cache(maxsize=32)
def load_file(name: str) -> tuple[tuple[float, ...], ...]:
    with open(SAMPLES / name, newline="") as handle:
        reader = csv.reader(handle)
        next(reader, None)
        return tuple(tuple(float(x) for x in row[:6]) for row in reader if len(row) >= 6)


def code_of(meta: dict) -> str:
    return str(meta["symbol"]).partition(":")[2]


class SampleProvider:
    id = "sample"
    kinds = ("stocks", "crypto", "gold", "forex", "funds")
    intervals = ("1h", "1d")

    def files_for(self, code: str) -> dict[str, str]:
        return {m["interval"]: name for name, m in manifest().items() if code_of(m) == code.split(":")[-1]}

    def make_info(self, code: str) -> SymbolInfo | None:
        metas = [m for m in manifest().values() if code_of(m) == code]
        if not metas:
            return None
        head = metas[0]
        return SymbolInfo(f"sample:{code}", head["name"], head["kind"], head["quote"], "sample",
                          sorted({m["interval"] for m in metas}), False)

    def all_infos(self) -> list[SymbolInfo]:
        codes = sorted({code_of(m) for m in manifest().values()})
        return [i for i in (self.make_info(c) for c in codes) if i]

    def search(self, query: str, kind: str) -> list[SymbolInfo]:
        needle = query.strip().lower()
        return [i for i in self.all_infos() if (kind in ("all", i.kind))
                and (needle in i.symbol.lower() or needle in i.name.lower())]

    def candles(self, code: str, interval: str, limit: int, start: float | None, end: float | None):
        name = self.files_for(code).get(interval)
        if name is None:
            raise MarketDataError(f"sample {code} has no {interval} data", 404)
        return clip([list(row) for row in load_file(name)], limit, start, end)

    def latest(self, code: str) -> Quote:
        info = self.make_info(code)
        if info is None:
            raise MarketDataError(f"unknown sample {code}", 404)
        interval = info.intervals[0]
        row = load_file(self.files_for(code)[interval])[-1]
        return Quote(f"sample:{code}", row[4], row[0], info.quote, True)

    def info(self, code: str) -> SymbolInfo | None:
        return self.make_info(code)

    def popular(self, kind: str) -> list[SymbolInfo]:
        return [i for i in self.all_infos() if i.kind == "stocks" and kind in ("all", "stocks")]


def clear_cache() -> None:
    manifest.cache_clear()
    load_file.cache_clear()
