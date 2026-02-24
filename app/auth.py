import hashlib
import hmac
import json
from urllib.parse import parse_qsl


def extract_telegram_id_from_init_data(init_data: str, bot_token: str) -> int:
    if not init_data:
        raise ValueError("Отсутствует initData")
    if not bot_token:
        raise ValueError("BOT_TOKEN не задан")

    parsed = dict(parse_qsl(init_data, keep_blank_values=True))
    provided_hash = parsed.pop("hash", "")
    if not provided_hash:
        raise ValueError("В initData отсутствует hash")

    data_check_string = "\n".join(f"{key}={value}" for key, value in sorted(parsed.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    calculated_hash = hmac.new(
        secret_key,
        data_check_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(calculated_hash, provided_hash):
        raise ValueError("Подпись initData не прошла проверку")

    user_payload = parsed.get("user")
    if not user_payload:
        raise ValueError("В initData отсутствуют данные пользователя")

    try:
        user_data = json.loads(user_payload)
    except json.JSONDecodeError as exc:
        raise ValueError("Некорректный формат user в initData") from exc

    telegram_id_raw = user_data.get("id")
    try:
        telegram_id = int(telegram_id_raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("В initData отсутствует корректный user.id") from exc
    if telegram_id <= 0:
        raise ValueError("Telegram ID должен быть положительным числом")
    return telegram_id
