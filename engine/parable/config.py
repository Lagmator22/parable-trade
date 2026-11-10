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

    anthropic_api_key: str = ""
    bot_model: str = "claude-haiku-5-5"
    claude_models: str = ""
    autoloops_api_key: str = ""
    jev_models: str = "gemma-4-31b-it,deepseek-v4.1-flash"
    gemini_api_key: str = ""
    gemini_models: str = ""
    gemma_models: str = ""


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
