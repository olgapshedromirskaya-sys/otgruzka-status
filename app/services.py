from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.enums import FINAL_STATUSES, MARKETPLACE_LABELS, STATUS_LABELS, Marketplace, OrderStatus
from app.models import Order, OrderEvent
from app.schemas import DashboardSummary, OrderCreate, OrderEventCreate


RETURN_STATUSES = {
    OrderStatus.RETURN_STARTED,
    OrderStatus.RETURN_IN_TRANSIT_FROM_BUYER,
    OrderStatus.RETURN_ARRIVED_TO_SELLER_PICKUP,
}


def _to_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def create_order(session: Session, payload: OrderCreate) -> Order:
    status_at = _to_aware_utc(payload.initial_status_at or datetime.now(timezone.utc))
    due_ship_at = _to_aware_utc(payload.due_ship_at) if payload.due_ship_at else None

    order = Order(
        marketplace=payload.marketplace,
        external_order_id=payload.external_order_id,
        product_name=payload.product_name,
        sku=payload.sku,
        quantity=payload.quantity,
        due_ship_at=due_ship_at,
        current_status=payload.initial_status,
        current_status_at=status_at,
        comment=payload.comment,
    )
    order.events.append(
        OrderEvent(
            status=payload.initial_status,
            event_at=status_at,
            note="Первичный статус заказа",
        )
    )
    session.add(order)
    session.commit()
    session.refresh(order)
    return order


def get_order_or_404(session: Session, order_id: int) -> Order:
    query = (
        select(Order)
        .where(Order.id == order_id)
        .options(selectinload(Order.events))
    )
    order = session.scalar(query)
    if not order:
        raise ValueError(f"Order {order_id} not found")
    return order


def add_order_event(session: Session, order: Order, payload: OrderEventCreate) -> Order:
    event_at = _to_aware_utc(payload.event_at)
    event = OrderEvent(
        order_id=order.id,
        status=payload.status,
        event_at=event_at,
        note=payload.note,
    )
    session.add(event)
    order.current_status = payload.status
    order.current_status_at = event_at
    session.add(order)
    session.commit()
    session.refresh(order)
    return get_order_or_404(session, order.id)


def list_orders(
    session: Session,
    marketplace: Optional[Marketplace] = None,
    status: Optional[OrderStatus] = None,
    search: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[Order], int]:
    filters = []
    if marketplace:
        filters.append(Order.marketplace == marketplace)
    if status:
        filters.append(Order.current_status == status)
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

    base_query = base_query.order_by(Order.current_status_at.desc()).limit(limit).offset(offset)
    items = list(session.scalars(base_query).all())
    total = session.scalar(count_query) or 0
    return items, total


def build_summary(session: Session, marketplace: Marketplace) -> DashboardSummary:
    now = datetime.now(timezone.utc)
    marketplace_filter = Order.marketplace == marketplace

    total_orders = session.scalar(select(func.count(Order.id)).where(marketplace_filter)) or 0
    active_orders = (
        session.scalar(
            select(func.count(Order.id)).where(
                marketplace_filter,
                Order.current_status.not_in(FINAL_STATUSES),
            )
        )
        or 0
    )
    overdue_to_ship = (
        session.scalar(
            select(func.count(Order.id)).where(
                marketplace_filter,
                Order.due_ship_at.is_not(None),
                Order.due_ship_at < now,
                Order.current_status.not_in(FINAL_STATUSES),
            )
        )
        or 0
    )

    buyout_count = (
        session.scalar(
            select(func.count(Order.id)).where(
                marketplace_filter, Order.current_status == OrderStatus.BUYOUT
            )
        )
        or 0
    )
    rejection_count = (
        session.scalar(
            select(func.count(Order.id)).where(
                marketplace_filter, Order.current_status == OrderStatus.REJECTION
            )
        )
        or 0
    )
    return_count = (
        session.scalar(
            select(func.count(Order.id)).where(
                marketplace_filter, Order.current_status.in_(RETURN_STATUSES)
            )
        )
        or 0
    )
    defect_count = (
        session.scalar(
            select(func.count(Order.id)).where(
                marketplace_filter, Order.current_status == OrderStatus.DEFECT
            )
        )
        or 0
    )

    grouped = session.execute(
        select(Order.current_status, func.count(Order.id))
        .where(marketplace_filter)
        .group_by(Order.current_status)
    ).all()

    by_status: dict[str, int] = {}
    for status, count in grouped:
        by_status[status.value] = count
    for status in OrderStatus:
        by_status.setdefault(status.value, 0)

    denominator = buyout_count + rejection_count
    buyout_rate = (buyout_count / denominator * 100.0) if denominator else 0.0

    return DashboardSummary(
        marketplace=marketplace,
        total_orders=total_orders,
        active_orders=active_orders,
        overdue_to_ship=overdue_to_ship,
        buyout_count=buyout_count,
        rejection_count=rejection_count,
        return_count=return_count,
        defect_count=defect_count,
        buyout_rate_percent=round(buyout_rate, 1),
        by_status=by_status,
    )


def status_catalog() -> list[dict[str, str]]:
    return [{"code": status.value, "name": STATUS_LABELS[status]} for status in OrderStatus]


def marketplace_catalog() -> list[dict[str, str]]:
    return [{"code": market.value, "name": MARKETPLACE_LABELS[market]} for market in Marketplace]

