import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient

from app.config import FunnelConfig, Settings
from app.db import Database
from app.web import create_app

TOKEN = "123456:TEST-token"


def sign_init_data(user_id: int, token: str = TOKEN, auth_date: int | None = None) -> str:
    """Формирует initData так же, как это делает Telegram."""
    fields = {
        "auth_date": str(auth_date or int(time.time())),
        "query_id": "AAH",
        "user": json.dumps({"id": user_id, "first_name": "Admin"}),
    }
    check_string = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


@pytest.fixture
def client(db: Database, cfg: FunnelConfig) -> TestClient:
    settings = Settings(bot_token=TOKEN, webapp_url=None, admin_ids=frozenset({42}))
    return TestClient(create_app(db, cfg, settings))


def test_index_served(client: TestClient) -> None:
    assert "Воронка регистраций" in client.get("/").text


def test_stats_requires_telegram(client: TestClient) -> None:
    assert client.get("/api/stats").status_code == 401


def test_stats_with_valid_admin(client: TestClient) -> None:
    r = client.get("/api/stats", headers={"Authorization": f"tma {sign_init_data(42)}"})
    assert r.status_code == 200
    assert r.json()["totals"]["started"] == 0


@pytest.mark.parametrize(
    "init_data",
    [
        sign_init_data(7),  # не админ
        sign_init_data(42, token="999:other-bot"),  # подпись чужого бота
        sign_init_data(42, auth_date=int(time.time()) - 2 * 86400),  # устарели
    ],
)
def test_stats_rejects_bad_init_data(client: TestClient, init_data: str) -> None:
    assert client.get("/api/stats", headers={"Authorization": f"tma {init_data}"}).status_code == 403


def test_dev_mode_skips_auth(db: Database, cfg: FunnelConfig) -> None:
    settings = Settings(bot_token=TOKEN, dev_mode=True)
    assert TestClient(create_app(db, cfg, settings)).get("/api/stats").status_code == 200
