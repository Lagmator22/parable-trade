BPS = 10_000
FRACTION = 1_000_000
VALUE_DIV = 10**10
SIDES = ("buy", "sell")


class RefereeError(Exception):
    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail


class Refusal(Exception):
    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


def return_bps(start_cash: int, final_equity: int) -> int:
    return (final_equity - start_cash) * BPS // start_cash


def drawdown_bps(peak: int, current: int) -> int:
    return max(0, (peak - current) * BPS // peak) if peak > 0 else 0


def holdings_value(units: int, price: int) -> int:
    return units * price // VALUE_DIV


def hundredths(bps: float) -> int:
    return int(round(bps * 100))


def fee_for(amount: int, fee_bps: float) -> int:
    return amount * hundredths(fee_bps) // FRACTION


def slipped(price: int, side: str, slippage_bps: float) -> int:
    slip = hundredths(slippage_bps)
    factor = FRACTION + slip if side == "buy" else FRACTION - slip
    return max(1, price * factor // FRACTION)


def check_order(side: str, amount: object, max_trade: int) -> int:
    if side not in SIDES:
        raise Refusal("BadAmount", f"unknown side {side!r}")
    if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
        raise Refusal("BadAmount", "amount must be a positive integer")
    if side == "buy" and amount > max_trade:
        raise Refusal("OverTradeLimit", f"limit is {max_trade}")
    return amount


def plan_buy(cash: int, amount: int, fill: int, fee: int) -> dict:
    if cash < amount + fee:
        raise Refusal("InsufficientCash", f"cash is {cash}")
    units = amount * VALUE_DIV // fill
    if units <= 0:
        raise Refusal("BadAmount", "amount too small to buy a unit")
    return {"amount": amount, "units_delta": units, "cash_delta": -(amount + fee), "fee": fee}


def plan_sell(held: int, amount: int, fill: int, fee_bps: float) -> dict:
    if held <= 0:
        raise Refusal("InsufficientUnits", "nothing to sell")
    units = min(held, -(-amount * VALUE_DIV // fill))
    proceeds = min(amount, holdings_value(units, fill))
    fee = fee_for(proceeds, fee_bps)
    return {"amount": proceeds, "units_delta": -units, "cash_delta": proceeds - fee, "fee": fee}


def plan_fill(run: dict, side: str, amount: int, price: int, fee_bps: float, slippage_bps: float) -> dict:
    fill = slipped(price, side, slippage_bps)
    if side == "buy":
        plan = plan_buy(run["cash_usd"], amount, fill, fee_for(amount, fee_bps))
    else:
        plan = plan_sell(run["units"], amount, fill, fee_bps)
    return {**plan, "price": fill}


def buy_amount(cash: int, max_trade: int, size_pct: float, fee_bps: float) -> int:
    sized = cash * hundredths(size_pct) // BPS
    room = cash * FRACTION // (FRACTION + hundredths(fee_bps))
    return min(max_trade, sized, room)


def sell_amount(units: int, price: int) -> int:
    return -(-units * price // VALUE_DIV)
