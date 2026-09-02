import pytest
from fastapi import HTTPException

from backend import app as backend_app
from backend import config


def test_password_hash_uses_memory_hard_scrypt():
    password_hash = backend_app._hash_password("a-safe-password")
    assert password_hash.startswith("scrypt$")
    assert backend_app._verify_password("a-safe-password", password_hash)
    assert not backend_app._verify_password("wrong-password", password_hash)


def test_provider_settings_are_per_user_and_never_return_plaintext(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PROVIDER_SETTINGS_DB_PATH", tmp_path / "provider_settings.sqlite3")
    monkeypatch.setattr(config, "LLM_PROVIDER", "openrouter")
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "")
    config.save_provider_settings("user-a", "openrouter", "secret-for-user-a", "model-a", True)

    public_settings = config.get_provider_settings("user-a")
    assert public_settings["openrouter"]["configured"] is True
    assert "api_key" not in public_settings["openrouter"]
    assert config.get_provider_settings("user-b")["openrouter"]["configured"] is False
    assert config.get_runtime_provider_config("user-a")["api_key"] == "secret-for-user-a"


def test_in_memory_rate_limit_rejects_over_limit(monkeypatch):
    backend_app._rate_limit_events.clear()
    monkeypatch.setattr(backend_app, "redis_client", None)
    backend_app._enforce_rate_limit("test", "user", 1)
    with pytest.raises(HTTPException) as error:
        backend_app._enforce_rate_limit("test", "user", 1)
    assert error.value.status_code == 429
