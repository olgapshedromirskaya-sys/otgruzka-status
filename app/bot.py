import asyncio
import logging

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup, WebAppInfo

from app.config import settings
from app.db import init_db, session_scope
from app.enums import MARKETPLACE_LABELS, STATUS_LABELS, Marketplace, OrderStatus
from app.services import build_summary

router = Router()


def _build_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Открыть дашборд", web_app=WebAppInfo(url=settings.webapp_url))],
            [KeyboardButton(text="Сводка WB"), KeyboardButton(text="Сводка Ozon")],
            [KeyboardButton(text="Сводка за сегодня")],
        ],
        resize_keyboard=True,
    )


def _summary_text(marketplace: Marketplace) -> str:
    with session_scope() as session:
        summary = build_summary(session, marketplace)

    lines = [
        f"<b>{MARKETPLACE_LABELS[marketplace]} · FBS</b>",
        f"Заказов: <b>{summary.total_orders}</b>",
        f"Активные: <b>{summary.active_orders}</b>",
        f"Просрочено к отгрузке: <b>{summary.overdue_to_ship}</b>",
        f"Выкупов: <b>{summary.buyout_count}</b>",
        f"Отказов: <b>{summary.rejection_count}</b>",
        f"Возвратов: <b>{summary.return_count}</b>",
        f"Брак: <b>{summary.defect_count}</b>",
        f"Процент выкупа: <b>{summary.buyout_rate_percent}%</b>",
        "",
        "<b>По текущим статусам:</b>",
    ]
    for status in OrderStatus:
        lines.append(f"• {STATUS_LABELS[status]}: {summary.by_status.get(status.value, 0)}")
    return "\n".join(lines)


@router.message(CommandStart())
async def start_handler(message: Message) -> None:
    await message.answer(
        (
            "Бот для FBS-отслеживания WB и Ozon.\n"
            "Откройте WebApp для карточек и событий по заказам,\n"
            "или запросите сводку кнопками ниже."
        ),
        reply_markup=_build_keyboard(),
    )


@router.message(Command("help"))
async def help_handler(message: Message) -> None:
    await message.answer(
        "Команды:\n"
        "/start — открыть меню\n"
        "/help — справка\n"
        "Кнопки «Сводка WB/Ozon» — быстрые метрики",
        reply_markup=_build_keyboard(),
    )


@router.message(F.text == "Сводка WB")
async def wb_summary_handler(message: Message) -> None:
    await message.answer(_summary_text(Marketplace.WB), parse_mode="HTML")


@router.message(F.text == "Сводка Ozon")
async def ozon_summary_handler(message: Message) -> None:
    await message.answer(_summary_text(Marketplace.OZON), parse_mode="HTML")


@router.message(F.text == "Сводка за сегодня")
async def full_summary_handler(message: Message) -> None:
    wb = _summary_text(Marketplace.WB)
    oz = _summary_text(Marketplace.OZON)
    await message.answer(f"{wb}\n\n{oz}", parse_mode="HTML")


async def run_bot() -> None:
    if not settings.bot_token:
        raise RuntimeError("Set BOT_TOKEN in .env before running bot.")

    init_db()
    logging.basicConfig(level=logging.INFO)
    bot = Bot(token=settings.bot_token)
    dp = Dispatcher()
    dp.include_router(router)
    await dp.start_polling(bot)


def main() -> None:
    asyncio.run(run_bot())


if __name__ == "__main__":
    main()

