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


def paypal_mocked() -> bool:
    s = get_settings()
    return s.parable_mock_paypal or not (s.paypal_client_id and s.paypal_client_secret)


def paypal_mode() -> str:
    if paypal_mocked():
        return "mock"
    return "live" if get_settings().paypal_env == "live" else "sandbox"
