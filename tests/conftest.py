from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from app.config import FunnelConfig, load_funnel_config
from app.db import Database

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def cfg() -> FunnelConfig:
    return load_funnel_config(ROOT / "config.yaml")


@pytest.fixture
async def db() -> AsyncIterator[Database]:
    database = await Database.connect(":memory:")
    yield database
    await database.close()


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Тесты не должны читать настоящий .env и переменные окружения разработчика."""
    for var in ("BOT_TOKEN", "WEBAPP_URL", "ADMIN_IDS", "DEV_MODE"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.chdir(tmp_path)
