import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.config import settings as app_settings
from app.db import session_scope
from app.enums import MARKETPLACE_LABELS, STATUS_LABELS, Marketplace, OrderStatus, UserRole
from app.models import Order, OrderEvent, Settings, User
from app.schemas import (
    DashboardSummary,
    OrderBrief,
    OrderEventRead,
    OrderRead,
    SettingsRead,
    SettingsUpdate,
    SyncReport,
    TodaySummary,
)

logger = logging.getLogger(__name__)

SYNC_LOCK = asyncio.Lock()
REQUEST_PAUSE_SECONDS = 0.45
MAX_WB_PAGES = 20
MAX_OZON_PAGES = 30
RECENT_ORDERS_DAYS = 30

WB_NEW_ORDERS_URL = "https://marketplace-api.wildberries.ru/api/v3/orders/new"
WB_ORDERS_URL = "https://marketplace-api.wildberries.ru/api/v3/orders"
OZON_FBS_LIST_URL = "https://api-seller.ozon.ru/v3/posting/fbs/list"


def get_user_by_telegram_id(session: Session, telegram_id: int) -> User | None:
    return session.get(User, telegram_id)


def list_users(session: Session) -> list[User]:
    items = list(session.scalars(select(User)).all())
    return sorted(
        items,
        key=lambda item: (0 if item.role == UserRole.OWNER else 1, item.added_at, item.telegram_id),
    )


def add_admin_user(session: Session, telegram_id: int, full_name: str, added_by: int) -> User:
    existing = get_user_by_telegram_id(session, telegram_id)
    if existing:
        raise ValueError("Пользователь с таким Telegram ID уже существует")

    user = User(
        telegram_id=telegram_id,
        role=UserRole.ADMIN,
        full_name=full_name.strip(),
        added_by=added_by,
    )
    session.add(user)
    session.flush()
    return user


def remove_user(session: Session, telegram_id: int) -> User | None:
    user = get_user_by_telegram_id(session, telegram_id)
    if not user:
        return None
    session.delete(user)
    session.flush()
    return user


def ensure_owner_user(session: Session) -> bool:
    users_total = int(session.scalar(select(func.count(User.telegram_id))) or 0)
    if users_total > 0:
        return False

    owner_telegram_id = app_settings.owner_telegram_id
    if owner_telegram_id is None:
        logger.warning("OWNER_TELEGRAM_ID не задан, owner-пользователь не создан")
        return False

    owner = User(
        telegram_id=owner_telegram_id,
        role=UserRole.OWNER,
        full_name="Руководитель",
        added_by=owner_telegram_id,
    )
    session.add(owner)
    session.flush()
    logger.info("Создан первый owner с Telegram ID %s", owner_telegram_id)
    return True


@dataclass(slots=True)
class ExternalOrderSnapshot:
    marketplace: Marketplace
    assembly_task_number: str
    status: OrderStatus
    status_at: datetime
    product_name: str
    sku: str | None
    quantity: int
    due_ship_at: datetime | None
    source_status: str


WB_SUPPLIER_STATUS_MAP: dict[str, OrderStatus] = {
    "new": OrderStatus.NEW,
    "confirm": OrderStatus.NEW,
    "complete": OrderStatus.BUYOUT,
    "cancel": OrderStatus.REJECTION,
}

OZON_STATUS_MAP: dict[str, OrderStatus] = {
    "awaiting_registration": OrderStatus.NEW,
    "acceptance_in_progress": OrderStatus.NEW,
    "awaiting_approve": OrderStatus.NEW,
    "awaiting_packaging": OrderStatus.ASSEMBLY,
    "awaiting_deliver": OrderStatus.TRANSFERRED_TO_DELIVERY,
    "driver_pickup": OrderStatus.TRANSFERRED_TO_DELIVERY,
    "sent_by_seller": OrderStatus.TRANSFERRED_TO_DELIVERY,
    "not_accepted": OrderStatus.REJECTION,
    "cancelled": OrderStatus.REJECTION,
    "delivering": OrderStatus.IN_TRANSIT_TO_BUYER,
    "delivered": OrderStatus.ARRIVED_AT_BUYER_PICKUP,
    "received": OrderStatus.BUYOUT,
    "returned": OrderStatus.RETURN_STARTED,
    "returning": OrderStatus.RETURN_IN_TRANSIT_FROM_BUYER,
    "returned_to_seller": OrderStatus.RETURN_ARRIVED_TO_SELLER_PICKUP,
    "seller_pickup": OrderStatus.SELLER_PICKED_UP,
    "loss": OrderStatus.DEFECT,
}


def _to_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_datetime(value: Any, fallback: datetime | None = None) -> datetime:
    if isinstance(value, datetime):
        return _to_aware_utc(value)
    if value is None:
        return fallback or datetime.now(timezone.utc)
    text = str(value).strip()
    if not text:
        return fallback or datetime.now(timezone.utc)
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
        return _to_aware_utc(parsed)
    except ValueError:
        pass

    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(text, fmt)
            return parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return fallback or datetime.now(timezone.utc)


def _safe_int(value: Any, default: int = 1) -> int:
    try:
        parsed = int(value)
        return parsed if parsed > 0 else default
    except (TypeError, ValueError):
        return default


def _log_marketplace_response(api_name: str, response: httpx.Response) -> None:
    request_url = str(response.request.url)
    logger.info("%s API ответ: url=%s status=%s", api_name, request_url, response.status_code)
    if response.is_error:
        body_preview = response.text[:200].replace("\n", "\\n")
        logger.error(
            "%s API ошибка: url=%s status=%s body[0:200]=%s",
            api_name,
            request_url,
            response.status_code,
            body_preview,
        )


def _payload_preview(payload: Any, limit: int = 500) -> str:
    try:
        serialized = json.dumps(payload, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        serialized = str(payload)

    preview = serialized[:limit].replace("\n", "\\n")
    if len(serialized) > limit:
        return f"{preview}..."
    return preview


def _extract_wb_orders(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []

    orders_payload = payload.get("orders") or payload.get("data") or []
    if isinstance(orders_payload, dict):
        orders_payload = orders_payload.get("orders", [])
    if not isinstance(orders_payload, list):
        return []

    return [item for item in orders_payload if isinstance(item, dict)]


def _normalize_status_text(raw_status: str | int | None) -> str:
    if raw_status is None:
        return ""
    return str(raw_status).strip().lower()


def _recent_period_utc(days: int = RECENT_ORDERS_DAYS) -> tuple[datetime, datetime]:
    now = datetime.now(timezone.utc)
    return now - timedelta(days=days), now


def _to_iso8601_utc(value: datetime) -> str:
    return _to_aware_utc(value).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _map_wb_status(raw_status: str | int | None) -> OrderStatus:
    normalized = _normalize_status_text(raw_status)
    return WB_SUPPLIER_STATUS_MAP.get(normalized, OrderStatus.NEW)


def _map_ozon_status(raw_status: str | int | None) -> OrderStatus:
    normalized = _normalize_status_text(raw_status)
    if normalized in OZON_STATUS_MAP:
        return OZON_STATUS_MAP[normalized]
    if "cancel" in normalized or "not_accepted" in normalized:
        return OrderStatus.REJECTION
    if "return" in normalized and "to_seller" in normalized:
        return OrderStatus.RETURN_ARRIVED_TO_SELLER_PICKUP
    if "return" in normalized:
        return OrderStatus.RETURN_STARTED
    if "deliver" in normalized or "transit" in normalized:
        return OrderStatus.IN_TRANSIT_TO_BUYER
    return OrderStatus.NEW


def _today_start_utc() -> datetime:
    try:
        tz = ZoneInfo(app_settings.timezone)
    except Exception:
        tz = timezone.utc
    now_local = datetime.now(tz)
    start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    return start_local.astimezone(timezone.utc)


def _event_note(source_status: str) -> str:
    normalized = source_status.strip()
    if not normalized:
        return "Синхронизация API"
    return f"Синхронизация API ({normalized})"


def _event_to_read(event: OrderEvent) -> OrderEventRead:
    return OrderEventRead(
        id=event.id,
        status=event.status,
        status_name=STATUS_LABELS[event.status],
        event_at=_to_aware_utc(event.event_at),
        note=event.note,
    )


def _order_to_read(order: Order) -> OrderRead:
    events = sorted(order.events, key=lambda item: item.event_at, reverse=True)
    return OrderRead(
        id=order.id,
        marketplace=order.marketplace,
        marketplace_name=MARKETPLACE_LABELS[order.marketplace],
        assembly_task_number=order.external_order_id,
        product_name=order.product_name,
        sku=order.sku,
        quantity=order.quantity,
        current_status=order.current_status,
        current_status_name=STATUS_LABELS[order.current_status],
        current_status_at=_to_aware_utc(order.current_status_at),
        created_at=_to_aware_utc(order.created_at),
        updated_at=_to_aware_utc(order.updated_at),
        events=[_event_to_read(event) for event in events],
    )


def status_catalog() -> list[dict[str, str]]:
    return [{"code": status.value, "name": STATUS_LABELS[status]} for status in OrderStatus]


def marketplace_catalog() -> list[dict[str, str]]:
    return [{"code": market.value, "name": MARKETPLACE_LABELS[market]} for market in Marketplace]


def _get_or_create_settings(session: Session) -> Settings:
    settings_entity = session.get(Settings, 1)
    if settings_entity:
        return settings_entity
    settings_entity = Settings(id=1, wb_token="", ozon_client_id="", ozon_api_key="")
    session.add(settings_entity)
    session.flush()
    return settings_entity


def get_settings(session: Session) -> SettingsRead:
    settings_entity = _get_or_create_settings(session)
    return SettingsRead(
        wb_token=settings_entity.wb_token or "",
        ozon_client_id=settings_entity.ozon_client_id or "",
        ozon_api_key=settings_entity.ozon_api_key or "",
        updated_at=settings_entity.updated_at,
    )


def save_settings(session: Session, payload: SettingsUpdate) -> SettingsRead:
    settings_entity = _get_or_create_settings(session)
    settings_entity.wb_token = payload.wb_token.strip()
    settings_entity.ozon_client_id = payload.ozon_client_id.strip()
    settings_entity.ozon_api_key = payload.ozon_api_key.strip()
    session.add(settings_entity)
    session.commit()
    session.refresh(settings_entity)
    return get_settings(session)


def list_orders(
    session: Session,
    marketplace: Marketplace | None = None,
    search: str | None = None,
    limit: int = 200,
    offset: int = 0,
) -> tuple[list[OrderRead], int]:
    filters = []
    if marketplace:
        filters.append(Order.marketplace == marketplace)
    if search:
        needle = f"%{search.strip()}%"
        filters.append(
            or_(
                Order.external_order_id.ilike(needle),
                Order.product_name.ilike(needle),
                Order.sku.ilike(needle),
            )
        )

    base_query = select(Order).options(selectinload(Order.events))
    count_query = select(func.count(Order.id))
    if filters:
        base_query = base_query.where(and_(*filters))
        count_query = count_query.where(and_(*filters))

    base_query = base_query.order_by(Order.current_status_at.desc(), Order.id.desc()).limit(limit).offset(offset)
    items = list(session.scalars(base_query).all())
    total = int(session.scalar(count_query) or 0)
    return ([_order_to_read(item) for item in items], total)


def list_recent_orders(session: Session, marketplace: Marketplace, limit: int = 10) -> list[OrderBrief]:
    query = (
        select(Order)
        .where(Order.marketplace == marketplace)
        .order_by(Order.current_status_at.desc(), Order.id.desc())
        .limit(limit)
    )
    items = list(session.scalars(query).all())
    return [
        OrderBrief(
            assembly_task_number=item.external_order_id,
            current_status=item.current_status,
            current_status_name=STATUS_LABELS[item.current_status],
            current_status_at=_to_aware_utc(item.current_status_at),
        )
        for item in items
    ]


def build_summary(session: Session, marketplace: Marketplace) -> DashboardSummary:
    today_start = _today_start_utc()
    market_filter = Order.marketplace == marketplace
    total_orders = int(session.scalar(select(func.count(Order.id)).where(market_filter)) or 0)
    updated_today = int(
        session.scalar(
            select(func.count(Order.id)).where(
                market_filter,
                Order.current_status_at >= today_start,
            )
        )
        or 0
    )
    grouped = (
        session.execute(
            select(Order.current_status, func.count(Order.id))
            .where(market_filter)
            .group_by(Order.current_status)
        )
        .all()
    )

    by_status: dict[str, int] = {STATUS_LABELS[status]: 0 for status in OrderStatus}
    for status, count in grouped:
        by_status[STATUS_LABELS[status]] = int(count)

    return DashboardSummary(
        marketplace=marketplace,
        marketplace_name=MARKETPLACE_LABELS[marketplace],
        total_orders=total_orders,
        updated_today=updated_today,
        by_status=by_status,
    )


def build_today_summary(session: Session) -> TodaySummary:
    today_start = _today_start_utc()
    wb_updates = int(
        session.scalar(
            select(func.count(Order.id)).where(
                Order.marketplace == Marketplace.WB,
                Order.current_status_at >= today_start,
            )
        )
        or 0
    )
    ozon_updates = int(
        session.scalar(
            select(func.count(Order.id)).where(
                Order.marketplace == Marketplace.OZON,
                Order.current_status_at >= today_start,
            )
        )
        or 0
    )

    return TodaySummary(
        date=today_start.date().isoformat(),
        wb_updates=wb_updates,
        ozon_updates=ozon_updates,
        total_updates=wb_updates + ozon_updates,
    )


def export_rows(session: Session) -> list[dict[str, str]]:
    query = select(Order).options(selectinload(Order.events)).order_by(Order.marketplace, Order.current_status_at.desc())
    orders = list(session.scalars(query).all())
    rows: list[dict[str, str]] = []
    for order in orders:
        events = sorted(order.events, key=lambda item: item.event_at)
        history = " | ".join(
            f"{STATUS_LABELS[event.status]} ({_to_aware_utc(event.event_at).strftime('%d.%m.%Y %H:%M')})"
            for event in events
        )
        rows.append(
            {
                "Маркетплейс": MARKETPLACE_LABELS[order.marketplace],
                "Номер сборочного задания": order.external_order_id,
                "Текущий статус": STATUS_LABELS[order.current_status],
                "Дата текущего статуса": _to_aware_utc(order.current_status_at).strftime("%d.%m.%Y %H:%M"),
                "История статусов": history,
            }
        )
    return rows


def _extract_wb_task_number(item: dict[str, Any]) -> str:
    return str(
        item.get("id")
        or item.get("orderId")
        or item.get("order_id")
        or item.get("rid")
        or item.get("srid")
        or ""
    ).strip()


def _normalize_wb_order(item: dict[str, Any]) -> ExternalOrderSnapshot | None:
    task_number = _extract_wb_task_number(item)
    if not task_number:
        return None

    raw_supplier_status = item.get("supplierStatus")
    logger.info("WB supplierStatus: order=%s supplierStatus=%r", task_number, raw_supplier_status)
    status = _map_wb_status(raw_supplier_status)
    status_at = _parse_datetime(
        item.get("updatedAt")
        or item.get("statusUpdatedAt")
        or item.get("createdAt")
    )
    due_ship_at = _parse_datetime(item.get("deadline") or item.get("shipmentDate"), fallback=status_at)

    skus = item.get("skus")
    sku = None
    if isinstance(skus, list) and skus:
        sku = str(skus[0])
    elif item.get("supplierArticle"):
        sku = str(item.get("supplierArticle"))
    elif item.get("chrtId"):
        sku = str(item.get("chrtId"))

    product_name = (
        str(item.get("subject") or item.get("nmName") or item.get("article") or "").strip()
        or f"Заказ WB {task_number}"
    )

    return ExternalOrderSnapshot(
        marketplace=Marketplace.WB,
        assembly_task_number=task_number[:128],
        status=status,
        status_at=status_at,
        product_name=product_name[:256],
        sku=sku[:128] if sku else None,
        quantity=_safe_int(item.get("quantity"), default=1),
        due_ship_at=due_ship_at,
        source_status=str(raw_supplier_status or ""),
    )


def _log_ozon_postings_preview(postings: list[dict[str, Any]]) -> None:
    preview: list[dict[str, str]] = []
    for item in postings[:3]:
        posting_id = item.get("posting_number") or item.get("order_number") or item.get("order_id") or item.get("id")
        preview.append({"id": str(posting_id or ""), "status": str(item.get("status") or "")})
    logger.info("Ozon API первые 3 заказа (id/статус): %s", preview)


def _normalize_ozon_order(item: dict[str, Any]) -> ExternalOrderSnapshot | None:
    task_number = str(item.get("posting_number") or item.get("order_number") or item.get("order_id") or "").strip()
    if not task_number:
        return None

    raw_status = item.get("status")
    status = _map_ozon_status(raw_status)
    status_at = _parse_datetime(
        item.get("in_process_at")
        or item.get("status_updated_at")
        or item.get("created_at")
    )
    due_ship_at = _parse_datetime(item.get("shipment_date"), fallback=status_at)

    products = item.get("products") if isinstance(item.get("products"), list) else []
    if products:
        first_product = products[0]
        product_name = str(first_product.get("name") or f"Отправление Ozon {task_number}")
        sku = str(first_product.get("offer_id") or first_product.get("sku") or "") or None
        quantity = sum(_safe_int(product.get("quantity"), default=1) for product in products)
    else:
        product_name = f"Отправление Ozon {task_number}"
        sku = None
        quantity = 1

    return ExternalOrderSnapshot(
        marketplace=Marketplace.OZON,
        assembly_task_number=task_number[:128],
        status=status,
        status_at=status_at,
        product_name=product_name[:256],
        sku=sku[:128] if sku else None,
        quantity=max(quantity, 1),
        due_ship_at=due_ship_at,
        source_status=str(raw_status or ""),
    )


async def _fetch_wb_orders(wb_token: str) -> list[ExternalOrderSnapshot]:
    headers = {"Authorization": wb_token.strip()}
    snapshots: list[ExternalOrderSnapshot] = []
    recent_from, _ = _recent_period_utc()
    next_cursor: int | str = 0

    logger.info(
        "WB синхронизация за последние %s дней: createdAt >= %s",
        RECENT_ORDERS_DAYS,
        _to_iso8601_utc(recent_from),
    )

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(WB_NEW_ORDERS_URL, headers=headers)
        _log_marketplace_response("WB", response)
        try:
            initial_payload: Any = response.json()
        except ValueError:
            initial_payload = response.text
        logger.info("WB API /orders/new JSON[0:500]=%s", _payload_preview(initial_payload))
        if response.status_code == 429:
            logger.warning("WB API вернул 429, ожидание перед повтором /orders/new")
            await asyncio.sleep(2.0)
            response = await client.get(WB_NEW_ORDERS_URL, headers=headers)
            _log_marketplace_response("WB", response)
            try:
                initial_payload = response.json()
            except ValueError:
                initial_payload = response.text
            logger.info("WB API /orders/new (retry) JSON[0:500]=%s", _payload_preview(initial_payload))
        response.raise_for_status()

        for item in _extract_wb_orders(initial_payload):
            normalized = _normalize_wb_order(item)
            if not normalized:
                continue
            created_at = _parse_datetime(item.get("createdAt"), fallback=normalized.status_at)
            if created_at < recent_from:
                logger.info(
                    "WB заказ пропущен (createdAt старше %s дней): id=%s createdAt=%s",
                    RECENT_ORDERS_DAYS,
                    normalized.assembly_task_number,
                    _to_iso8601_utc(created_at),
                )
                continue
            snapshots.append(normalized)

        for _ in range(MAX_WB_PAGES):
            params: dict[str, Any] = {"limit": 1000, "next": next_cursor}

            response = await client.get(WB_ORDERS_URL, headers=headers, params=params)
            _log_marketplace_response("WB", response)
            try:
                payload: Any = response.json()
            except ValueError:
                payload = response.text
            logger.info(
                "WB API /orders JSON[next=%s][0:500]=%s",
                next_cursor,
                _payload_preview(payload),
            )
            if response.status_code == 429:
                logger.warning("WB API вернул 429, ожидание перед повтором страницы")
                await asyncio.sleep(2.0)
                continue
            response.raise_for_status()

            orders_payload = _extract_wb_orders(payload)
            if not orders_payload:
                break

            for item in orders_payload:
                normalized = _normalize_wb_order(item)
                if not normalized:
                    continue
                created_at = _parse_datetime(item.get("createdAt"), fallback=normalized.status_at)
                if created_at < recent_from:
                    logger.info(
                        "WB заказ пропущен (createdAt старше %s дней): id=%s createdAt=%s",
                        RECENT_ORDERS_DAYS,
                        normalized.assembly_task_number,
                        _to_iso8601_utc(created_at),
                    )
                    continue
                snapshots.append(normalized)

            new_next = payload.get("next") if isinstance(payload, dict) else None
            if new_next in (None, "", 0) or new_next == next_cursor:
                break
            next_cursor = new_next
            await asyncio.sleep(REQUEST_PAUSE_SECONDS)
    return snapshots


async def _fetch_ozon_orders(ozon_client_id: str, ozon_api_key: str) -> list[ExternalOrderSnapshot]:
    headers = {
        "Client-Id": ozon_client_id.strip(),
        "Api-Key": ozon_api_key.strip(),
        "Content-Type": "application/json",
    }
    snapshots: list[ExternalOrderSnapshot] = []
    offset = 0
    limit = 50
    since_dt, to_dt = _recent_period_utc()
    since_iso = _to_iso8601_utc(since_dt)
    to_iso = _to_iso8601_utc(to_dt)

    logger.info(
        "Ozon синхронизация за последние %s дней: since=%s to=%s",
        RECENT_ORDERS_DAYS,
        since_iso,
        to_iso,
    )

    async with httpx.AsyncClient(timeout=30.0) as client:
        for _ in range(MAX_OZON_PAGES):
            body = {
                "dir": "ASC",
                "filter": {
                    "since": since_iso,
                    "to": to_iso,
                },
                "limit": limit,
                "offset": offset,
                "with": {
                    "analytics_data": False,
                    "financial_data": False,
                },
            }

            response = await client.post(OZON_FBS_LIST_URL, headers=headers, json=body)
            _log_marketplace_response("Ozon", response)
            if response.status_code == 429:
                logger.warning("Ozon API вернул 429, ожидание перед повтором страницы")
                await asyncio.sleep(2.0)
                continue
            response.raise_for_status()

            payload = response.json()
            result = payload.get("result") or {}
            postings = result.get("postings") or []
            if not isinstance(postings, list):
                break

            postings_dicts = [item for item in postings if isinstance(item, dict)]
            _log_ozon_postings_preview(postings_dicts)

            for item in postings_dicts:
                normalized = _normalize_ozon_order(item)
                if normalized:
                    snapshots.append(normalized)

            has_next = bool(result.get("has_next"))
            if not has_next or not postings:
                break
            offset += limit
            await asyncio.sleep(REQUEST_PAUSE_SECONDS)
    return snapshots


def _collapse_snapshots(items: list[ExternalOrderSnapshot]) -> list[ExternalOrderSnapshot]:
    collapsed: dict[tuple[Marketplace, str], ExternalOrderSnapshot] = {}
    for item in items:
        key = (item.marketplace, item.assembly_task_number)
        current = collapsed.get(key)
        if not current or item.status_at >= current.status_at:
            collapsed[key] = item
    return list(collapsed.values())


def _is_duplicate_event(order: Order, status: OrderStatus, event_at: datetime) -> bool:
    for event in order.events:
        if event.status != status:
            continue
        delta = abs((_to_aware_utc(event.event_at) - event_at).total_seconds())
        if delta < 1:
            return True
    return False


def _upsert_snapshot(session: Session, snapshot: ExternalOrderSnapshot) -> tuple[bool, bool]:
    query = (
        select(Order)
        .where(
            Order.marketplace == snapshot.marketplace,
            Order.external_order_id == snapshot.assembly_task_number,
        )
        .options(selectinload(Order.events))
        .order_by(Order.id.desc())
    )
    order = session.scalar(query)
    created = False
    event_created = False

    if not order:
        order = Order(
            marketplace=snapshot.marketplace,
            external_order_id=snapshot.assembly_task_number,
            product_name=snapshot.product_name,
            sku=snapshot.sku,
            quantity=max(snapshot.quantity, 1),
            due_ship_at=snapshot.due_ship_at,
            current_status=snapshot.status,
            current_status_at=snapshot.status_at,
            comment="Синхронизация API WB/Ozon",
        )
        order.events.append(
            OrderEvent(
                status=snapshot.status,
                event_at=snapshot.status_at,
                note=_event_note(snapshot.source_status),
            )
        )
        session.add(order)
        created = True
        event_created = True
        return created, event_created

    order.product_name = snapshot.product_name or order.product_name
    if snapshot.sku:
        order.sku = snapshot.sku
    order.quantity = max(snapshot.quantity, 1)
    order.due_ship_at = snapshot.due_ship_at or order.due_ship_at

    should_create_event = False
    if order.current_status != snapshot.status:
        should_create_event = True
    elif snapshot.status_at > _to_aware_utc(order.current_status_at) + timedelta(seconds=1):
        should_create_event = True

    if should_create_event and not _is_duplicate_event(order, snapshot.status, snapshot.status_at):
        order.events.append(
            OrderEvent(
                status=snapshot.status,
                event_at=snapshot.status_at,
                note=_event_note(snapshot.source_status),
            )
        )
        order.current_status = snapshot.status
        order.current_status_at = snapshot.status_at
        event_created = True
    elif snapshot.status_at > _to_aware_utc(order.current_status_at):
        order.current_status_at = snapshot.status_at

    session.add(order)
    return created, event_created


async def sync_orders_from_marketplaces() -> SyncReport:
    if SYNC_LOCK.locked():
        return SyncReport(
            wb_received=0,
            ozon_received=0,
            processed_orders=0,
            created_orders=0,
            updated_orders=0,
            created_events=0,
            message="Синхронизация уже выполняется",
        )

    async with SYNC_LOCK:
        with session_scope() as session:
            cfg = get_settings(session)
            wb_token = cfg.wb_token
            ozon_client_id = cfg.ozon_client_id
            ozon_api_key = cfg.ozon_api_key

        wb_snapshots: list[ExternalOrderSnapshot] = []
        ozon_snapshots: list[ExternalOrderSnapshot] = []

        try:
            if wb_token:
                wb_snapshots = await _fetch_wb_orders(wb_token)
                await asyncio.sleep(REQUEST_PAUSE_SECONDS)
        except Exception:
            logger.exception("Не удалось получить заказы WB")

        try:
            if ozon_client_id and ozon_api_key:
                ozon_snapshots = await _fetch_ozon_orders(ozon_client_id, ozon_api_key)
        except Exception:
            logger.exception("Не удалось получить заказы Ozon")

        all_snapshots = _collapse_snapshots([*wb_snapshots, *ozon_snapshots])
        created_orders = 0
        updated_orders = 0
        created_events = 0

        with session_scope() as session:
            for snapshot in all_snapshots:
                created, event_created = _upsert_snapshot(session, snapshot)
                if created:
                    created_orders += 1
                else:
                    updated_orders += 1
                if event_created:
                    created_events += 1

        return SyncReport(
            wb_received=len(wb_snapshots),
            ozon_received=len(ozon_snapshots),
            processed_orders=len(all_snapshots),
            created_orders=created_orders,
            updated_orders=updated_orders,
            created_events=created_events,
            message="Синхронизация завершена",
        )

