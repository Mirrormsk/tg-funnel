import asyncio
import contextlib
import logging
import sys

import uvicorn
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand
from pydantic import ValidationError

from app.bot import router
from app.config import Settings, load_funnel_config
from app.db import Database
from app.scheduler import Scheduler
from app.web import create_app

log = logging.getLogger("funnel")


async def run(settings: Settings) -> None:
    cfg = load_funnel_config(settings.config_path)
    db = await Database.connect(settings.db_path)

    bot = Bot(settings.bot_token.get_secret_value(), default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(cfg=cfg, db=db, settings=settings)
    dp.include_router(router)
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Регистрация"),
            BotCommand(command="stats", description="Дашборд воронки"),
        ]
    )

    app = create_app(db, cfg, settings)
    server = uvicorn.Server(uvicorn.Config(app, host=settings.host, port=settings.port))
    me = await bot.get_me()
    log.info(
        "Бот @%s, дашборд http://%s:%s, шагов в цепочке: %s",
        me.username,
        settings.host,
        settings.port,
        len(cfg.schedule),
    )

    # Бот, планировщик и веб-сервер живут в одном процессе и одном event loop.
    # Ctrl+C останавливает uvicorn, после чего гасим остальное.
    tasks = [
        asyncio.create_task(dp.start_polling(bot, handle_signals=False)),
        asyncio.create_task(Scheduler(bot, db).run()),
    ]
    try:
        await server.serve()
    finally:
        for t in tasks:
            t.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.gather(*tasks, return_exceptions=True)
        await bot.session.close()
        await db.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        settings = Settings()  # значения из окружения и .env
    except ValidationError as e:
        # Показываем, какие переменные неверны, но не их значения — там может быть токен
        fields = ", ".join(".".join(map(str, err["loc"])).upper() for err in e.errors())
        sys.exit(f"Ошибка конфигурации в .env: {fields}. Образец — .env.example")
    asyncio.run(run(settings))


if __name__ == "__main__":
    main()
