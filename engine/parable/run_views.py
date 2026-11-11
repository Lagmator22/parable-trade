PUBLIC_RUN_KEYS = (
    "id", "seller_id", "listing_id", "purchase_id", "purpose", "name", "status", "cause", "spec_hash", "symbol",
    "interval", "quote", "start_cash_usd", "peak_equity_usd", "final_equity_usd", "equity_usd", "units", "pnl_bps",
    "drawdown_bps", "started_at", "expires_at", "ended_at", "trades", "refusals", "seconds_left", "lifetime_s",
)


HIDDEN_FOR_OTHERS = ("seller_id", "purchase_id")


def public_run(run: dict, viewer_id: str | None = None) -> dict:
    shown = {key: run.get(key) for key in PUBLIC_RUN_KEYS}
    if run.get("purpose") != "track" and viewer_id != run.get("seller_id"):
        for key in HIDDEN_FOR_OTHERS:
            shown[key] = None
    return shown


def run_visible(run: dict, viewer_id: str | None) -> bool:
    from parable.db import one

    if viewer_id is not None and run.get("seller_id") == viewer_id:
        return True
    if run.get("purpose") not in ("track", "probation") or not run.get("listing_id"):
        return False
    listing = one("SELECT active FROM listings WHERE id = ?", (run["listing_id"],))
    return bool(listing and listing["active"])
