import pytest
from fastapi.testclient import TestClient

from parable import api, identity
from parable.config import get_settings, startup_problems

STRONG = "x" * 40


def settle(monkeypatch, **env):
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()


def test_missing_keys_without_flag_is_a_problem(monkeypatch):
    settle(monkeypatch, PARABLE_MOCK_PAYPAL="0")
    assert any("PayPal keys" in problem for problem in startup_problems())


def test_app_refuses_to_start_without_keys_or_flag(monkeypatch, tmp_path):
    settle(monkeypatch, PARABLE_MOCK_PAYPAL="0")
    with pytest.raises(RuntimeError):
        with TestClient(api.create_app(tmp_path)):
            pass


def test_explicit_flag_allows_offline_dev(monkeypatch):
    settle(monkeypatch, PARABLE_MOCK_PAYPAL="1")
    assert startup_problems() == []


def test_production_refuses_mock_sim_and_weak_secret(monkeypatch):
    settle(monkeypatch, PARABLE_ENV="production", PARABLE_MOCK_PAYPAL="1", PRICE_SOURCE="sim", SESSION_SECRET="short")
    text = " ".join(startup_problems())
    assert "PARABLE_MOCK_PAYPAL" in text and "PRICE_SOURCE" in text and "SESSION_SECRET" in text


def test_production_with_keys_and_strong_secret_is_clean(monkeypatch):
    settle(
        monkeypatch, PARABLE_ENV="production", PARABLE_MOCK_PAYPAL="0", PRICE_SOURCE="live",
        SESSION_SECRET=STRONG, PAYPAL_CLIENT_ID="id", PAYPAL_CLIENT_SECRET="secret",
    )
    assert startup_problems() == []


def test_production_refuses_empty_secret(monkeypatch):
    settle(
        monkeypatch, PARABLE_ENV="production", PARABLE_MOCK_PAYPAL="0", PRICE_SOURCE="live",
        SESSION_SECRET="", PAYPAL_CLIENT_ID="id", PAYPAL_CLIENT_SECRET="secret",
    )
    assert any("SESSION_SECRET" in problem for problem in startup_problems())


def test_secret_key_rejects_placeholder_and_short(monkeypatch):
    settle(monkeypatch, PARABLE_MOCK_PAYPAL="0", SESSION_SECRET="replace-with-a-long-random-text")
    with pytest.raises(RuntimeError):
        identity.secret_key()
    settle(monkeypatch, PARABLE_MOCK_PAYPAL="0", SESSION_SECRET="tooshort")
    with pytest.raises(RuntimeError):
        identity.secret_key()
    settle(monkeypatch, PARABLE_MOCK_PAYPAL="0", SESSION_SECRET=STRONG)
    assert identity.secret_key() == STRONG


def test_secret_key_allows_placeholder_in_mock_mode(monkeypatch):
    settle(monkeypatch, PARABLE_MOCK_PAYPAL="1", SESSION_SECRET="replace-with-a-long-random-text")
    assert identity.secret_key() == "replace-with-a-long-random-text"
