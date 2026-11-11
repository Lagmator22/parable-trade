from parable.errors import LabError

PRIVATE_PROVIDERS = ("sample", "upload")


def provider_of(symbol: str) -> str:
    return str(symbol).partition(":")[0]


def is_live_symbol(symbol: str) -> bool:
    return provider_of(symbol) not in PRIVATE_PROVIDERS


def require_live_symbol(symbol: str, what: str) -> None:
    if not is_live_symbol(symbol):
        raise LabError(400, "bad_request", f"{what} needs live market data; sample and uploaded data cannot be used")


def require_instant_mode(symbol: str, mode: str) -> None:
    if mode != "instant" and not is_live_symbol(symbol):
        raise LabError(400, "bad_request",
                       "listings on sample or uploaded data can only be sold in instant mode, "
                       "because a hold trial must run on live market data")
