import csv
import io
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import Depends, FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from openpyxl import Workbook
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_session, init_db
from app.enums import Marketplace
from app.schemas import (
    DashboardSummary,
    OrdersResponse,
    SettingsRead,
    SettingsUpdate,
    StatusCatalogItem,
    SyncReport,
)
from app.services import (
    build_summary,
    export_rows,
    get_settings,
    list_orders,
    marketplace_catalog,
    save_settings,
    status_catalog,
    sync_orders_from_marketplaces,
)

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

app = FastAPI(title=settings.app_name, version="0.2.0")
static_dir = Path(__file__).resolve().parent / "static"

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=static_dir), name="static")

bot_instance = None
dp_instance = None
scheduler: AsyncIOScheduler | None = None


async def _scheduled_sync_job() -> None:
    report = await sync_orders_from_marketplaces()
    logger.info(
        "Плановая синхронизация: WB=%s Ozon=%s обработано=%s",
        report.wb_received,
        report.ozon_received,
        report.processed_orders,
    )


def _start_scheduler() -> None:
    global scheduler
    if scheduler and scheduler.running:
        return

    scheduler = AsyncIOScheduler(timezone=settings.timezone)
    scheduler.add_job(
        _scheduled_sync_job,
        trigger="interval",
        minutes=15,
        id="wb-ozon-fbs-sync",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=600,
    )
    scheduler.start()
    logger.info("APScheduler запущен (интервал: 15 минут)")


@app.on_event("startup")
async def startup_event() -> None:
    global bot_instance, dp_instance
    init_db()
    _start_scheduler()

    if settings.bot_token and settings.webapp_url:
        from app.bot import get_bot, get_dispatcher

        bot_instance = get_bot()
        dp_instance = get_dispatcher()
        webhook_url = f"{settings.webapp_url}/webhook"
        await bot_instance.delete_webhook(drop_pending_updates=True)
        await bot_instance.set_webhook(webhook_url)
        logger.info("Webhook set to %s", webhook_url)


@app.on_event("shutdown")
async def shutdown_event() -> None:
    if scheduler and scheduler.running:
        scheduler.shutdown(wait=False)
    if bot_instance:
        await bot_instance.session.close()


@app.post("/webhook")
async def telegram_webhook(request: Request) -> dict:
    from aiogram.types import Update

    if bot_instance and dp_instance:
        data = await request.json()
        update = Update.model_validate(data)
        await dp_instance.feed_update(bot_instance, update)
    return {"ok": True}


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
def serve_web_app() -> FileResponse:
    return FileResponse(static_dir / "index.html")


@app.get("/api/meta/statuses", response_model=list[StatusCatalogItem])
def get_statuses() -> list[StatusCatalogItem]:
    return status_catalog()


@app.get("/api/meta/marketplaces")
def get_marketplaces() -> list[dict[str, str]]:
    return marketplace_catalog()


@app.get("/api/orders", response_model=OrdersResponse)
def list_orders_endpoint(
    marketplace: Optional[Marketplace] = Query(default=None),
    search: Optional[str] = Query(default=None, max_length=128),
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> OrdersResponse:
    items, total = list_orders(
        session=session,
        marketplace=marketplace,
        search=search,
        limit=limit,
        offset=offset,
    )
    return OrdersResponse(items=items, total=total)


@app.get("/api/dashboard/{marketplace}", response_model=DashboardSummary)
def dashboard_marketplace_endpoint(
    marketplace: Marketplace, session: Session = Depends(get_session)
) -> DashboardSummary:
    return build_summary(session, marketplace)


@app.get("/api/dashboard")
def dashboard_all_endpoint(session: Session = Depends(get_session)) -> list[DashboardSummary]:
    return [build_summary(session, marketplace) for marketplace in Marketplace]


@app.get("/api/settings", response_model=SettingsRead)
def settings_read_endpoint(session: Session = Depends(get_session)) -> SettingsRead:
    return get_settings(session)


@app.put("/api/settings", response_model=SettingsRead)
def settings_update_endpoint(payload: SettingsUpdate, session: Session = Depends(get_session)) -> SettingsRead:
    return save_settings(session, payload)


@app.post("/api/sync/run", response_model=SyncReport)
async def run_sync_endpoint() -> SyncReport:
    return await sync_orders_from_marketplaces()


@app.get("/api/export/orders.csv")
def export_orders_csv_endpoint(session: Session = Depends(get_session)) -> StreamingResponse:
    rows = export_rows(session)
    columns = [
        "Маркетплейс",
        "Номер сборочного задания",
        "Текущий статус",
        "Дата текущего статуса",
        "История статусов",
    ]

    csv_buffer = io.StringIO()
    writer = csv.DictWriter(csv_buffer, fieldnames=columns, delimiter=";")
    writer.writeheader()
    writer.writerows(rows)

    filename = f"orders_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    payload = io.BytesIO(csv_buffer.getvalue().encode("utf-8-sig"))
    return StreamingResponse(
        payload,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/export/orders.xlsx")
def export_orders_xlsx_endpoint(session: Session = Depends(get_session)) -> StreamingResponse:
    rows = export_rows(session)
    columns = [
        "Маркетплейс",
        "Номер сборочного задания",
        "Текущий статус",
        "Дата текущего статуса",
        "История статусов",
    ]

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Заказы"
    sheet.append(columns)
    for row in rows:
        sheet.append([row[column] for column in columns])

    sheet.freeze_panes = "A2"
    widths = [18, 28, 30, 24, 90]
    for idx, width in enumerate(widths, start=1):
        column_letter = chr(64 + idx)
        sheet.column_dimensions[column_letter].width = width

    stream = io.BytesIO()
    workbook.save(stream)
    stream.seek(0)

    filename = f"orders_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return StreamingResponse(
        stream,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
