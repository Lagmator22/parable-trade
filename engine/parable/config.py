from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    paypal_client_id: str = ""
    paypal_client_secret: str = ""
    paypal_env: str = "sandbox"
    paypal_webhook_id: str = ""
    parable_mock_paypal: bool = False
    parable_env: str = ""
    demo_payout_email: str = ""
    trust_proxy: bool = False
    public_base_url: str = "http://localhost:8000"
    session_secret: str = ""
    platform_fee_bps: int = 1000
    database_path: str = "parable.db"
    price_source: str = "live"
    bot_interval_s: float = 15
    ai_analyst_brain: str = "gemini:gemini-3.5-flash-lite"
    parable_demo_seed: bool = False

    anthropic_api_key: str = ""
    bot_model: str = "claude-haiku-5-5"
    claude_models: str = ""
    autoloops_api_key: str = ""
    jev_models: str = "gemma-4-31b-it,deepseek-v4.1-flash"
    gemini_api_key: str = ""
    gemini_models: str = ""
    gemma_models: str = ""

    twelve_data_key: str = ""
    markets_offline: bool = False
    ai_free_tries_per_day: int = 5
    upload_max_bytes: int = 5_000_000
    upload_max_rows: int = 200_000
    max_live_runs_per_account: int = 5
    max_run_points_per_run: int = 20_000
    max_agents_per_account: int = 50
    max_versions_per_agent: int = 100
    max_datasets_per_account: int = 20
    max_listings_per_account: int = 10
    max_jobs_per_account: int = 2
    benchmark_max_models: int = 6
    rate_lab_per_minute: int = 30
    rate_ai_per_minute: int = 10
    rate_proofs_per_hour: int = 30
    rate_purchases_per_hour: int = 20
    track_lease_seconds: int = 2_592_000
    run_start_cash: int = 10_000_000_000


@lru_cache
def get_settings() -> Settings:
    return Settings()


PLACEHOLDER_SECRET = "replace-with-a-long-random-text"
MIN_SECRET_LENGTH = 32


def paypal_mocked() -> bool:
    return get_settings().parable_mock_paypal


def is_production() -> bool:
    return get_settings().parable_env.strip().lower() == "production"


def weak_secret(secret: str) -> bool:
    return len(secret) < MIN_SECRET_LENGTH or secret == PLACEHOLDER_SECRET


def startup_problems() -> list[str]:
    s = get_settings()
    problems = []
    has_keys = bool(s.paypal_client_id and s.paypal_client_secret)
    if not s.parable_mock_paypal and not has_keys:
        problems.append("PayPal keys are missing: set PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET, or set PARABLE_MOCK_PAYPAL=1 for offline development")
    if is_production():
        if s.parable_mock_paypal:
            problems.append("PARABLE_MOCK_PAYPAL=1 is not allowed when PARABLE_ENV=production")
        if s.price_source == "sim":
            problems.append("PRICE_SOURCE=sim is not allowed when PARABLE_ENV=production")
        if weak_secret(s.session_secret):
            problems.append("SESSION_SECRET must be at least 32 random characters when PARABLE_ENV=production")
    return problems


def paypal_mode() -> str:
    if paypal_mocked():
        return "mock"
    return "live" if get_settings().paypal_env == "live" else "sandbox"
