ENGINE_VERSION = "lab-1"

INTERVAL_SECONDS = {
    "1s": 1, "1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800,
    "1h": 3600, "2h": 7200, "4h": 14400, "6h": 21600, "8h": 28800, "12h": 43200,
    "1d": 86400, "3d": 259200, "1w": 604800,
}
INTERVALS = tuple(INTERVAL_SECONDS)
ASSET_KINDS = ("crypto", "stocks", "funds", "forex", "gold", "mine")
SOURCE_KINDS = ("market", "sample", "creator")
PROOF_KINDS = ("backtest", "rerun", "testdrive", "benchmark")
RUN_PURPOSES = ("practice", "probation", "track")

SECONDS_PER_YEAR = 31_557_600
BACKTEST_CASH = 10_000.0
TRAIN_FRACTION = 0.7
CURVE_MAX = 600
SPARKLINE_MAX = 60
MIN_BARS = 30
MAX_BARS = 20_000
MAX_BARS_STORED = 100_000
DECIMALS = 6

MAX_FORMULA_LEN = 400
MAX_AST_DEPTH = 12
MAX_AST_NODES = 120
MAX_PERIOD = 500
MAX_PARAMS = 12
MAX_PARAM_VALUES = 50
MAX_GRID = 500
MAX_POW = 4
MAX_SPEC_BYTES = 8_000
MAX_STEPS_CHARS = 4_000
