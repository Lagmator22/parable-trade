from parable.lab.markets import MarketDataError, Quote, SymbolInfo


class UploadProvider:
    id = "upload"
    kinds = ("mine",)
    intervals = ("1d",)

    def search(self, query: str, kind: str) -> list[SymbolInfo]:
        return []

    def candles(self, code: str, interval: str, limit: int, start: float | None, end: float | None):
        raise MarketDataError("uploaded data is private to its owner", 404)

    def latest(self, code: str) -> Quote:
        raise MarketDataError("uploaded data is private to its owner", 404)

    def info(self, code: str) -> SymbolInfo | None:
        return None

    def popular(self, kind: str) -> list[SymbolInfo]:
        return []
