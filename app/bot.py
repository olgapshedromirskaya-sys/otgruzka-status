from datetime import datetime

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command, CommandStart
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup, WebAppInfo

from app.config import settings
from app.db import session_scope
from app.enums import MARKETPLACE_LABELS, USER_ROLE_LABELS, Marketplace, UserRole
from app.models import User
from app.services import (
    add_admin_user,
    build_summary,
    build_today_summary,
    get_user_by_telegram_id,
    list_recent_orders,
    list_users,
    remove_user,
)

router = Router()

ACCESS_DENIED_TEXT = "У вас нет доступа. Обратитесь к руководителю."
OWNER_ONLY_TEXT = "Команда доступна только руководителю."


def get_bot() -> Bot:
    return Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode="HTML"),
    )


def get_dispatcher() -> Dispatcher:
    dp = Dispatcher()
    dp.include_router(router)
    return dp


def _build_keyboard(role: UserRole) -> ReplyKeyboardMarkup:
    dashboard_button = (
        KeyboardButton(text="Открыть дашборд", web_app=WebAppInfo(url=settings.webapp_url))
        if settings.webapp_url
        else KeyboardButton(text="Открыть дашборд")
    )
    keyboard = [
        [KeyboardButton(text="Заказы WB"), KeyboardButton(text="Заказы Ozon")],
        [KeyboardButton(text="Сводка за сегодня"), dashboard_button],
        [KeyboardButton(text="Настройки")],
    ]
    if role == UserRole.OWNER:
        keyboard.append([KeyboardButton(text="/users")])

    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
    )


async def _require_user(message: Message, owner_only: bool = False) -> User | None:
    if not message.from_user:
        await message.answer("Не удалось определить Telegram ID пользователя.")
        return None

    with session_scope() as session:
        user = get_user_by_telegram_id(session, message.from_user.id)

    if not user:
        await message.answer(ACCESS_DENIED_TEXT)
        return None

    if owner_only and user.role != UserRole.OWNER:
        await message.answer(OWNER_ONLY_TEXT)
        return None

    return user


def _orders_text(marketplace: Marketplace) -> str:
    with session_scope() as session:
        orders = list_recent_orders(session, marketplace, limit=10)

    if not orders:
        return (
            f"<b>{MARKETPLACE_LABELS[marketplace]}</b>\n"
            "Пока нет заказов.\n\n"
            "Откройте дашборд и добавьте API-ключи, затем дождитесь синхронизации."
        )

    lines = [
        f"<b>{MARKETPLACE_LABELS[marketplace]} · последние 10 заказов</b>",
        "",
        "<b>Номер сборочного задания — текущий статус</b>",
    ]
    for order in orders:
        dt = order.current_status_at.strftime("%d.%m.%Y %H:%M")
        lines.append(f"• №<b>{order.assembly_task_number}</b> — {order.current_status_name} ({dt})")
    return "\n".join(lines)


def _today_summary_text() -> str:
    with session_scope() as session:
        daily = build_today_summary(session)
        wb = build_summary(session, Marketplace.WB)
        ozon = build_summary(session, Marketplace.OZON)

    return (
        f"<b>Сводка за сегодня ({daily.date})</b>\n\n"
        f"WB: обновлений за сегодня — <b>{daily.wb_updates}</b>, всего заказов — <b>{wb.total_orders}</b>\n"
        f"Ozon: обновлений за сегодня — <b>{daily.ozon_updates}</b>, всего заказов — <b>{ozon.total_orders}</b>\n"
        f"\nИтого обновлений: <b>{daily.total_updates}</b>"
    )


def _help_text(role: UserRole) -> str:
    lines = [
        "Команды:",
        "/start — открыть меню",
        "/help — справка",
        "",
        "Кнопки меню:",
        "Заказы WB — последние 10 заказов WB",
        "Заказы Ozon — последние 10 заказов Ozon",
        "Сводка за сегодня — обновления заказов за день",
        "Открыть дашборд — запуск WebApp внутри Telegram",
        "Настройки — как добавить API-ключи",
    ]
    if role == UserRole.OWNER:
        lines.extend(
            [
                "",
                "Команды руководителя:",
                "/addadmin [telegram_id] [имя] — добавить администратора",
                "/removeuser [telegram_id] — удалить пользователя",
                "/users — список пользователей",
            ]
        )
    return "\n".join(lines)


@router.message(CommandStart())
async def start_handler(message: Message) -> None:
    user = await _require_user(message)
    if not user:
        return

    lines = [
        "Бот отслеживания FBS-заказов WB и Ozon.",
        f"Ваша роль: <b>{USER_ROLE_LABELS[user.role]}</b>.",
        "Используйте кнопки ниже для просмотра заказов, сводки и WebApp.",
    ]
    if user.role == UserRole.OWNER:
        lines.append(
            "Команды руководителя: /addadmin [telegram_id] [имя], /removeuser [telegram_id], /users."
        )

    await message.answer(
        "\n".join(lines),
        reply_markup=_build_keyboard(user.role),
    )


@router.message(Command("help"))
async def help_handler(message: Message) -> None:
    user = await _require_user(message)
    if not user:
        return
    await message.answer(
        _help_text(user.role),
        reply_markup=_build_keyboard(user.role),
    )


@router.message(Command("addadmin"))
async def add_admin_handler(message: Message) -> None:
    owner = await _require_user(message, owner_only=True)
    if not owner:
        return

    parts = (message.text or "").split(maxsplit=2)
    if len(parts) < 3:
        await message.answer("Формат команды: /addadmin [telegram_id] [имя]")
        return

    telegram_id_raw = parts[1].strip()
    full_name = parts[2].strip()
    if not full_name:
        await message.answer("Укажите имя администратора. Формат: /addadmin [telegram_id] [имя]")
        return
    if len(full_name) > 256:
        await message.answer("Имя слишком длинное. Максимум 256 символов.")
        return

    try:
        telegram_id = int(telegram_id_raw)
    except ValueError:
        await message.answer("Telegram ID должен быть целым числом.")
        return
    if telegram_id <= 0:
        await message.answer("Telegram ID должен быть положительным числом.")
        return

    try:
        with session_scope() as session:
            add_admin_user(
                session=session,
                telegram_id=telegram_id,
                full_name=full_name,
                added_by=owner.telegram_id,
            )
    except ValueError as exc:
        await message.answer(str(exc))
        return

    await message.answer(
        f"Пользователь <b>{full_name}</b> (ID: <code>{telegram_id}</code>) добавлен как Администратор."
    )


@router.message(Command("removeuser"))
async def remove_user_handler(message: Message) -> None:
    owner = await _require_user(message, owner_only=True)
    if not owner:
        return

    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Формат команды: /removeuser [telegram_id]")
        return

    try:
        telegram_id = int(parts[1].strip())
    except ValueError:
        await message.answer("Telegram ID должен быть целым числом.")
        return
    if telegram_id <= 0:
        await message.answer("Telegram ID должен быть положительным числом.")
        return
    if telegram_id == owner.telegram_id:
        await message.answer("Нельзя удалить самого себя.")
        return

    with session_scope() as session:
        user = get_user_by_telegram_id(session, telegram_id)
        if not user:
            await message.answer("Пользователь с таким Telegram ID не найден.")
            return
        if user.role == UserRole.OWNER:
            await message.answer("Нельзя удалить пользователя с ролью Руководитель.")
            return

        removed_name = user.full_name
        remove_user(session, telegram_id)

    await message.answer(
        f"Пользователь <b>{removed_name}</b> (ID: <code>{telegram_id}</code>) удалён."
    )


@router.message(Command("users"))
async def users_handler(message: Message) -> None:
    owner = await _require_user(message, owner_only=True)
    if not owner:
        return

    with session_scope() as session:
        users = list_users(session)

    if not users:
        await message.answer("Список пользователей пуст.")
        return

    lines = ["<b>Пользователи:</b>"]
    for user in users:
        added_at = user.added_at
        added_at_text = (
            added_at.strftime("%d.%m.%Y %H:%M")
            if isinstance(added_at, datetime)
            else "—"
        )
        added_by_text = f"{user.added_by}" if user.added_by is not None else "система"
        lines.append(
            "• "
            f"<b>{user.full_name}</b> — {USER_ROLE_LABELS[user.role]} "
            f"(ID: <code>{user.telegram_id}</code>, добавлен: {added_at_text}, кем: {added_by_text})"
        )

    await message.answer("\n".join(lines))


@router.message(F.text == "Заказы WB")
async def wb_orders_handler(message: Message) -> None:
    user = await _require_user(message)
    if not user:
        return
    await message.answer(_orders_text(Marketplace.WB))


@router.message(F.text == "Заказы Ozon")
async def ozon_orders_handler(message: Message) -> None:
    user = await _require_user(message)
    if not user:
        return
    await message.answer(_orders_text(Marketplace.OZON))


@router.message(F.text == "Сводка за сегодня")
async def full_summary_handler(message: Message) -> None:
    user = await _require_user(message)
    if not user:
        return
    await message.answer(_today_summary_text())


@router.message(F.text == "Настройки")
async def settings_help_handler(message: Message) -> None:
    user = await _require_user(message)
    if not user:
        return
    await message.answer(
        "Чтобы добавить API-ключи WB и Ozon:\n"
        "1) Нажмите кнопку «Открыть дашборд» в меню бота\n"
        "2) Перейдите во вкладку «Настройки»\n"
        "3) Заполните WB Token, Ozon Client ID и Ozon API Key\n"
        "4) Нажмите «Сохранить настройки»\n\n"
        "После сохранения синхронизация заказов запускается автоматически каждые 15 минут."
    )
