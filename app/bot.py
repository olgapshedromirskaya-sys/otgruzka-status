from datetime import datetime
from html import escape

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    WebAppInfo,
)

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
ADD_EMPLOYEE_ROLE_ADMIN = "add_employee_role:admin"
DELETE_USER_PREFIX = "delete_user:"


class AddEmployeeStates(StatesGroup):
    waiting_telegram_id = State()
    waiting_full_name = State()
    waiting_role = State()


def get_bot() -> Bot:
    return Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode="HTML"),
    )


def get_dispatcher() -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())
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
        keyboard.append([KeyboardButton(text="👥 Добавить сотрудника"), KeyboardButton(text="👥 Сотрудники")])

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


def _build_add_employee_role_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="👔 Администратор",
                    callback_data=ADD_EMPLOYEE_ROLE_ADMIN,
                )
            ]
        ]
    )


def _build_user_delete_keyboard(telegram_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="❌ Удалить",
                    callback_data=f"{DELETE_USER_PREFIX}{telegram_id}",
                )
            ]
        ]
    )


def _format_user_card(user: User) -> str:
    added_at = user.added_at
    added_at_text = added_at.strftime("%d.%m.%Y %H:%M") if isinstance(added_at, datetime) else "—"
    added_by_text = f"{user.added_by}" if user.added_by is not None else "система"
    text = (
        f"<b>{escape(user.full_name)}</b>\n"
        f"Роль: {USER_ROLE_LABELS[user.role]}\n"
        f"Telegram ID: <code>{user.telegram_id}</code>\n"
        f"Добавлен: {added_at_text}\n"
        f"Кем добавлен: {added_by_text}"
    )
    if user.role == UserRole.OWNER:
        text += "\nУдаление недоступно для руководителя."
    return text


async def _send_users_with_actions(message: Message) -> None:
    with session_scope() as session:
        users = list_users(session)

    if not users:
        await message.answer("Список пользователей пуст.")
        return

    await message.answer("<b>Сотрудники:</b>")
    for user in users:
        reply_markup = None
        if user.role != UserRole.OWNER:
            reply_markup = _build_user_delete_keyboard(user.telegram_id)
        await message.answer(_format_user_card(user), reply_markup=reply_markup)


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
                "",
                "Кнопки руководителя:",
                "👥 Добавить сотрудника — пошаговое добавление через диалог",
                "👥 Сотрудники — список пользователей с кнопками удаления",
            ]
        )
    return "\n".join(lines)


@router.message(CommandStart())
async def start_handler(message: Message, state: FSMContext) -> None:
    await state.clear()
    user = await _require_user(message)
    if not user:
        return

    lines = [
        "Бот отслеживания FBS-заказов WB и Ozon.",
        f"Ваша роль: <b>{USER_ROLE_LABELS[user.role]}</b>.",
        "Используйте кнопки ниже для просмотра заказов, сводки и WebApp.",
    ]
    if user.role == UserRole.OWNER:
        lines.append("Для управления доступом используйте кнопки «👥 Добавить сотрудника» и «👥 Сотрудники».")

    await message.answer(
        "\n".join(lines),
        reply_markup=_build_keyboard(user.role),
    )


@router.message(Command("help"))
async def help_handler(message: Message, state: FSMContext) -> None:
    await state.clear()
    user = await _require_user(message)
    if not user:
        return
    await message.answer(
        _help_text(user.role),
        reply_markup=_build_keyboard(user.role),
    )


@router.message(F.text == "👥 Добавить сотрудника")
async def add_employee_dialog_start_handler(message: Message, state: FSMContext) -> None:
    owner = await _require_user(message, owner_only=True)
    if not owner:
        return

    await state.clear()
    await state.set_state(AddEmployeeStates.waiting_telegram_id)
    await message.answer("Введите Telegram ID сотрудника:")


@router.message(AddEmployeeStates.waiting_telegram_id)
async def add_employee_collect_telegram_id_handler(message: Message, state: FSMContext) -> None:
    owner = await _require_user(message, owner_only=True)
    if not owner:
        await state.clear()
        return

    telegram_id_raw = (message.text or "").strip()
    try:
        telegram_id = int(telegram_id_raw)
    except ValueError:
        await message.answer("Telegram ID должен быть целым числом. Введите Telegram ID сотрудника:")
        return
    if telegram_id <= 0:
        await message.answer("Telegram ID должен быть положительным числом. Введите Telegram ID сотрудника:")
        return

    with session_scope() as session:
        exists = get_user_by_telegram_id(session, telegram_id)
    if exists:
        await message.answer("Пользователь с таким Telegram ID уже существует. Введите другой Telegram ID:")
        return

    await state.update_data(telegram_id=telegram_id)
    await state.set_state(AddEmployeeStates.waiting_full_name)
    await message.answer("Введите имя сотрудника:")


@router.message(AddEmployeeStates.waiting_full_name)
async def add_employee_collect_full_name_handler(message: Message, state: FSMContext) -> None:
    owner = await _require_user(message, owner_only=True)
    if not owner:
        await state.clear()
        return

    full_name = (message.text or "").strip()
    if not full_name:
        await message.answer("Имя не может быть пустым. Введите имя сотрудника:")
        return
    if len(full_name) > 256:
        await message.answer("Имя слишком длинное. Максимум 256 символов. Введите имя сотрудника:")
        return

    await state.update_data(full_name=full_name)
    await state.set_state(AddEmployeeStates.waiting_role)
    await message.answer(
        "Выберите роль сотрудника:",
        reply_markup=_build_add_employee_role_keyboard(),
    )


@router.message(AddEmployeeStates.waiting_role)
async def add_employee_waiting_role_message_handler(message: Message) -> None:
    owner = await _require_user(message, owner_only=True)
    if not owner:
        return
    await message.answer(
        "Нажмите кнопку «👔 Администратор», чтобы завершить добавление сотрудника.",
        reply_markup=_build_add_employee_role_keyboard(),
    )


@router.callback_query(AddEmployeeStates.waiting_role, F.data == ADD_EMPLOYEE_ROLE_ADMIN)
async def add_employee_select_role_handler(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user:
        await callback.answer("Не удалось определить Telegram ID пользователя.", show_alert=True)
        await state.clear()
        return

    with session_scope() as session:
        owner = get_user_by_telegram_id(session, callback.from_user.id)
    if not owner:
        await callback.answer(ACCESS_DENIED_TEXT, show_alert=True)
        await state.clear()
        return
    if owner.role != UserRole.OWNER:
        await callback.answer(OWNER_ONLY_TEXT, show_alert=True)
        await state.clear()
        return

    data = await state.get_data()
    telegram_id = data.get("telegram_id")
    full_name = str(data.get("full_name", "")).strip()
    if not isinstance(telegram_id, int) or telegram_id <= 0 or not full_name:
        if callback.message:
            await callback.message.answer("Диалог добавления сотрудника сброшен. Нажмите «👥 Добавить сотрудника» снова.")
        await callback.answer()
        await state.clear()
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
        if callback.message:
            await callback.message.answer(str(exc))
        await callback.answer()
        await state.clear()
        return

    if callback.message:
        await callback.message.answer(
            f"✅ Сотрудник {escape(full_name)} добавлен с ролью Администратор. "
            "Пусть напишет /start боту для получения доступа."
        )

    await callback.answer()
    await state.clear()


@router.callback_query(F.data == ADD_EMPLOYEE_ROLE_ADMIN)
async def add_employee_role_stale_callback_handler(callback: CallbackQuery) -> None:
    await callback.answer(
        "Диалог добавления сотрудника уже завершён. Нажмите «👥 Добавить сотрудника» для нового добавления.",
        show_alert=True,
    )


@router.message(F.text == "👥 Сотрудники")
async def users_menu_handler(message: Message) -> None:
    owner = await _require_user(message, owner_only=True)
    if not owner:
        return
    await _send_users_with_actions(message)


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
    await _send_users_with_actions(message)


@router.callback_query(F.data.startswith(DELETE_USER_PREFIX))
async def delete_user_button_handler(callback: CallbackQuery) -> None:
    if not callback.from_user:
        await callback.answer("Не удалось определить Telegram ID пользователя.", show_alert=True)
        return

    with session_scope() as session:
        owner = get_user_by_telegram_id(session, callback.from_user.id)
    if not owner:
        await callback.answer(ACCESS_DENIED_TEXT, show_alert=True)
        return
    if owner.role != UserRole.OWNER:
        await callback.answer(OWNER_ONLY_TEXT, show_alert=True)
        return

    telegram_id_raw = (callback.data or "").removeprefix(DELETE_USER_PREFIX)
    try:
        telegram_id = int(telegram_id_raw)
    except ValueError:
        await callback.answer("Некорректный Telegram ID для удаления.", show_alert=True)
        return
    if telegram_id <= 0:
        await callback.answer("Некорректный Telegram ID для удаления.", show_alert=True)
        return
    if telegram_id == owner.telegram_id:
        await callback.answer("Нельзя удалить самого себя.", show_alert=True)
        return

    with session_scope() as session:
        user = get_user_by_telegram_id(session, telegram_id)
        if not user:
            await callback.answer("Пользователь уже удалён или не найден.", show_alert=True)
            return
        if user.role == UserRole.OWNER:
            await callback.answer("Нельзя удалить пользователя с ролью Руководитель.", show_alert=True)
            return
        removed_name = user.full_name
        remove_user(session, telegram_id)

    if callback.message:
        await callback.message.edit_text(
            f"✅ Сотрудник {escape(removed_name)} удалён (ID: <code>{telegram_id}</code>)."
        )
    await callback.answer("Пользователь удалён.")


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
