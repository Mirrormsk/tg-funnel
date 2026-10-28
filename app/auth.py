import time

from aiogram.utils.web_app import WebAppInitData, safe_parse_webapp_init_data


class AuthError(Exception):
    pass


def validate_init_data(
    init_data: str,
    bot_token: str,
    admin_ids: frozenset[int],
    max_age: int = 24 * 3600,
    now: float | None = None,
) -> WebAppInitData:
    """Проверяет подпись initData от Telegram Mini App и права доступа к дашборду."""
    try:
        data = safe_parse_webapp_init_data(bot_token, init_data)
    except ValueError as e:
        raise AuthError("Неверная подпись initData") from e

    if (now or time.time()) - data.auth_date.timestamp() > max_age:
        raise AuthError("initData устарели — откройте дашборд заново")
    if admin_ids and (data.user is None or data.user.id not in admin_ids):
        raise AuthError("Нет доступа к дашборду")
    return data
