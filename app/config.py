from pathlib import Path
from typing import Annotated

import yaml
from pydantic import BaseModel, Field, HttpUrl, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Messages(BaseModel):
    greeting: str
    phone_request: str
    phone_button: str
    phone_received: str
    already_registered: str
    not_own_contact: str
    remind_phone: str


class ScheduledStep(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9_]+$")
    title: str
    delay_seconds: int = Field(ge=0)
    text: str


class FunnelConfig(BaseModel):
    """Тексты и тайминги воронки из config.yaml."""

    messages: Messages
    schedule: list[ScheduledStep]

    @field_validator("schedule")
    @classmethod
    def unique_ids(cls, steps: list[ScheduledStep]) -> list[ScheduledStep]:
        ids = [s.id for s in steps]
        if len(ids) != len(set(ids)):
            raise ValueError("id шагов в schedule должны быть уникальными")
        return steps


def load_funnel_config(path: str | Path) -> FunnelConfig:
    with Path(path).open(encoding="utf-8") as f:
        return FunnelConfig.model_validate(yaml.safe_load(f))


class Settings(BaseSettings):
    """Секреты и параметры окружения: переменные окружения или файл .env (не коммитится)."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore", frozen=True)

    # SecretStr не даёт токену попасть в логи, repr и трейсбеки: печатается как '**********'
    bot_token: SecretStr
    webapp_url: HttpUrl | None = None
    admin_ids: Annotated[frozenset[int], NoDecode] = frozenset()
    db_path: str = "data/funnel.db"
    config_path: Path = Path("config.yaml")
    host: str = "127.0.0.1"
    port: int = Field(default=8080, ge=1, le=65535)
    timezone: str = "Europe/Moscow"
    dev_mode: bool = False

    @field_validator("webapp_url", mode="before")
    @classmethod
    def empty_url_is_none(cls, v: object) -> object:
        return v or None

    @field_validator("webapp_url")
    @classmethod
    def https_only(cls, v: HttpUrl | None) -> HttpUrl | None:
        if v is not None and v.scheme != "https":
            raise ValueError("Telegram открывает Mini App только по HTTPS")
        return v

    @field_validator("admin_ids", mode="before")
    @classmethod
    def parse_admin_ids(cls, v: object) -> object:
        # ADMIN_IDS=111,222 — привычнее, чем JSON-список
        if isinstance(v, str):
            return frozenset(int(x) for x in v.split(",") if x.strip())
        return v
