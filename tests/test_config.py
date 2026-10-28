from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import FunnelConfig, Settings

TOKEN = "123456:SECRET-token-value"


def test_config_yaml_is_valid(cfg: FunnelConfig) -> None:
    assert [s.delay_seconds for s in cfg.schedule] == [10, 60]
    assert "{name}" in cfg.messages.greeting


def test_duplicate_step_ids_rejected(cfg: FunnelConfig) -> None:
    data = cfg.model_dump()
    data["schedule"].append(data["schedule"][0])
    with pytest.raises(ValidationError):
        FunnelConfig.model_validate(data)


def test_settings_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", TOKEN)
    monkeypatch.setenv("ADMIN_IDS", "111, 222")
    monkeypatch.setenv("WEBAPP_URL", "https://demo.trycloudflare.com")
    s = Settings()
    assert s.admin_ids == {111, 222}
    assert s.bot_token.get_secret_value() == TOKEN


def test_settings_read_dotenv_file() -> None:
    # isolated_env перенёс нас во временную папку — кладём .env туда
    Path(".env").write_text(f"BOT_TOKEN={TOKEN}\nWEBAPP_URL=\n", encoding="utf-8")
    s = Settings()
    assert s.bot_token.get_secret_value() == TOKEN
    assert s.webapp_url is None


def test_token_never_leaks_into_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", TOKEN)
    s = Settings()
    assert TOKEN not in repr(s)
    assert TOKEN not in str(s.model_dump())


def test_token_is_required() -> None:
    with pytest.raises(ValidationError, match="bot_token"):
        Settings()


def test_webapp_url_must_be_https(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", TOKEN)
    monkeypatch.setenv("WEBAPP_URL", "http://localhost:8080")
    with pytest.raises(ValidationError, match="HTTPS"):
        Settings()
