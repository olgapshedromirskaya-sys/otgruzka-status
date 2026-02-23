from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command, CommandStart
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup

from app.config import settings
from app.db import session_scope
from app.enums import MARKETPLACE_LABELS, Marketplace
from app.services import build_summary, build_today_summary, list_recent_orders

router = Router()


def get_bot() -> Bot:
    return Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode="HTML"),
    )


def get_dispatcher() -> Dispatcher:
    dp = Dispatcher()
    dp.include_router(router)
    return dp


def _build_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Заказы WB"), KeyboardButton(text="Заказы Ozon")],
            [KeyboardButton(text="Сводка за сегодня"), KeyboardButton(text="Настройки")],
        ],
        resize_keyboard=True,
    )


def _orders_text(marketplace: Marketplace) -> str:
    with session_scope() as session:
        orders = list_recent_orders(session, marketplace, limit=10)

    if not orders:
        return (
            f"<b>{MARKETPLACE_LABELS[marketplace]}</b>\n"
            "Пока нет заказов.\n\n"
            "Добавьте API-ключи в дашборде и дождитесь синхронизации."
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


@router.message(CommandStart())
async def start_handler(message: Message) -> None:
    await message.answer(
        "Бот отслеживания FBS-заказов WB и Ozon.\n"
        "Используйте кнопки ниже для просмотра заказов и сводки.",
        reply_markup=_build_keyboard(),
    )


@router.message(Command("help"))
async def help_handler(message: Message) -> None:
    await message.answer(
        "Команды:\n"
        "/start — открыть меню\n"
        "/help — справка\n\n"
        "Кнопки меню:\n"
        "Заказы WB — последние 10 заказов WB\n"
        "Заказы Ozon — последние 10 заказов Ozon\n"
        "Сводка за сегодня — обновления заказов за день\n"
        "Настройки — как добавить API-ключи",
        reply_markup=_build_keyboard(),
    )


@router.message(F.text == "Заказы WB")
async def wb_orders_handler(message: Message) -> None:
    await message.answer(_orders_text(Marketplace.WB))


@router.message(F.text == "Заказы Ozon")
async def ozon_orders_handler(message: Message) -> None:
    await message.answer(_orders_text(Marketplace.OZON))


@router.message(F.text == "Сводка за сегодня")
async def full_summary_handler(message: Message) -> None:
    await message.answer(_today_summary_text())


@router.message(F.text == "Настройки")
async def settings_help_handler(message: Message) -> None:
    await message.answer(
        "Чтобы добавить API-ключи WB и Ozon:\n"
        f"1) Откройте дашборд: {settings.webapp_url}\n"
        "2) Перейдите во вкладку «Настройки»\n"
        "3) Заполните WB Token, Ozon Client ID и Ozon API Key\n"
        "4) Нажмите «Сохранить настройки»\n\n"
        "После сохранения синхронизация заказов запускается автоматически каждые 15 минут."
    )
