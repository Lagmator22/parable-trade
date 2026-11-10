from parable.lab import datasets
from parable.lab.markets import MarketDataError, Quote, SymbolInfo
from parable.lab.providers.base import clip


class UploadProvider:
    id = "upload"
    kinds = ("mine",)
    intervals = ("1d",)

    def search(self, query: str, kind: str) -> list[SymbolInfo]:
        return []

    def make_info(self, row: dict) -> SymbolInfo:
        return SymbolInfo(f"upload:{row['id']}", row["name"], "mine", row["quote"], "upload", [row["interval"]], False)

    def row(self, code: str) -> dict:
        found = datasets.raw_dataset(code)
        if found is None:
            raise MarketDataError(f"unknown dataset {code}", 404)
        return found

    def candles(self, code: str, interval: str, limit: int, start: float | None, end: float | None):
        found = self.row(code)
        if interval != found["interval"]:
            raise MarketDataError(f"that dataset only has {found['interval']} bars", 404)
        return clip(found["bars"], limit, start, end)

    def latest(self, code: str) -> Quote:
        found = self.row(code)
        last = found["bars"][-1]
        return Quote(f"upload:{code}", last[4], last[0], found["quote"], True)

    def info(self, code: str) -> SymbolInfo | None:
        found = datasets.raw_dataset(code)
        return self.make_info(found) if found else None

    def popular(self, kind: str) -> list[SymbolInfo]:
        return []
