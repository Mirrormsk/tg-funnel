import time
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse

from app.auth import AuthError, validate_init_data
from app.config import FunnelConfig, Settings
from app.db import Database

INDEX = Path(__file__).resolve().parent.parent / "webapp" / "index.html"


def create_app(db: Database, cfg: FunnelConfig, settings: Settings) -> FastAPI:
    app = FastAPI(title="Funnel dashboard", docs_url=None, redoc_url=None)

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(INDEX, headers={"Cache-Control": "no-store"})

    @app.get("/healthz")
    async def healthz() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/api/stats")
    async def stats(authorization: Annotated[str | None, Header()] = None) -> dict[str, Any]:
        # Mini App присылает подписанные Telegram данные в заголовке "Authorization: tma <initData>"
        if not settings.dev_mode:
            scheme, _, init_data = (authorization or "").partition(" ")
            if scheme.lower() != "tma" or not init_data:
                raise HTTPException(401, "Откройте дашборд из Telegram")
            try:
                validate_init_data(init_data, settings.bot_token.get_secret_value(), settings.admin_ids)
            except AuthError as e:
                raise HTTPException(403, str(e)) from e
        return await db.stats(cfg.schedule, settings.timezone, time.time())

    return app
