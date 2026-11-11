PUBLIC_RUN_KEYS = (
    "id", "seller_id", "listing_id", "purchase_id", "purpose", "name", "status", "cause", "spec_hash", "symbol",
    "interval", "quote", "start_cash_usd", "peak_equity_usd", "final_equity_usd", "equity_usd", "units", "pnl_bps",
    "drawdown_bps", "started_at", "expires_at", "ended_at", "trades", "refusals", "seconds_left", "lifetime_s",
)


def public_run(run: dict) -> dict:
    return {key: run.get(key) for key in PUBLIC_RUN_KEYS}
