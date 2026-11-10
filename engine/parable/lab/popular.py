from parable.lab.consts import INTERVALS

BINANCE_INTERVALS = list(INTERVALS)
STOCK_INTERVALS = ["1m", "5m", "15m", "30m", "1h", "1d", "1w"]
TWELVE_INTERVALS = ["1m", "5m", "15m", "30m", "1h", "4h", "1d", "1w"]

CRYPTO = (("BTCUSDT", "Bitcoin"), ("ETHUSDT", "Ethereum"), ("SOLUSDT", "Solana"),
          ("BNBUSDT", "BNB"), ("XRPUSDT", "XRP"), ("DOGEUSDT", "Dogecoin"))
FOREX = (("EURUSD", "Euro / US Dollar", "USD"), ("GBPUSD", "British Pound / US Dollar", "USD"),
         ("USDJPY", "US Dollar / Japanese Yen", "JPY"), ("USDINR", "US Dollar / Indian Rupee", "INR"),
         ("AUDUSD", "Australian Dollar / US Dollar", "USD"))
STOCKS = (("AAPL", "Apple"), ("MSFT", "Microsoft"), ("NVDA", "NVIDIA"), ("TSLA", "Tesla"),
          ("SPY", "SPDR S&P 500 ETF"), ("QQQ", "Invesco QQQ ETF"))
FUNDS = (("125497", "SBI Small Cap Fund - Direct - Growth"),
         ("122639", "Parag Parikh Flexi Cap Fund - Direct - Growth"),
         ("119063", "HDFC Nifty 50 Index Fund - Direct - Growth"),
         ("118778", "Nippon India Small Cap Fund - Direct - Growth"),
         ("118825", "Mirae Asset Large Cap Fund - Direct - Growth"),
         ("120586", "ICICI Prudential Large Cap Fund - Direct - Growth"))


def popular_static(kind: str, stock_provider: str = "yahoo"):
    from parable.lab.markets import SymbolInfo

    def info(provider, code, name, kind_, quote, intervals):
        return SymbolInfo(f"{provider}:{code}", name, kind_, quote, provider, list(intervals), True)

    out = []
    if kind in ("crypto", "all"):
        out += [info("binance", c, n, "crypto", "USDT", BINANCE_INTERVALS) for c, n in CRYPTO]
    if kind in ("gold", "all"):
        out.append(info("binance", "PAXGUSDT", "Gold (PAX Gold)", "gold", "USDT", BINANCE_INTERVALS))
    if kind in ("forex", "all"):
        out += [info("fx", c, n, "forex", q, ["1d"]) for c, n, q in FOREX]
    if kind in ("stocks", "all"):
        iv = TWELVE_INTERVALS if stock_provider == "twelve" else STOCK_INTERVALS
        out += [info(stock_provider, c, n, "stocks", "USD", iv) for c, n in STOCKS]
    if kind in ("funds", "all"):
        out += [info("mfapi", c, n, "funds", "INR", ["1d"]) for c, n in FUNDS]
    return out
