from datetime import datetime, timedelta, timezone
from random import randint

from sqlalchemy import select

from app.db import init_db, session_scope
from app.enums import Marketplace, OrderStatus
from app.models import Order, OrderEvent


STATUS_FLOW = [
    OrderStatus.NEW,
    OrderStatus.ASSEMBLY,
    OrderStatus.TRANSFERRED_TO_DELIVERY,
    OrderStatus.ACCEPTED_AT_WAREHOUSE,
    OrderStatus.IN_TRANSIT_TO_BUYER,
    OrderStatus.ARRIVED_AT_BUYER_PICKUP,
    OrderStatus.BUYOUT,
]


def _seed_marketplace(marketplace: Marketplace) -> None:
    now = datetime.now(timezone.utc)
    titles = [
        ("Лосины женские S", "WB-784"),
        ("Рюкзак городской 22л", "WB-912"),
        ("Термос 500мл", "WB-445"),
    ]
    with session_scope() as session:
        existing = session.scalar(select(Order.id).where(Order.marketplace == marketplace))
        if existing:
            return

        for index, (name, sku) in enumerate(titles, start=1):
            base_date = now - timedelta(days=randint(1, 7))
            order = Order(
                marketplace=marketplace,
                external_order_id=f"{marketplace.value.upper()}-{index:04d}",
                product_name=name,
                sku=sku if marketplace == Marketplace.WB else sku.replace("WB", "OZ"),
                quantity=randint(1, 3),
                due_ship_at=base_date + timedelta(hours=8),
                current_status=OrderStatus.NEW,
                current_status_at=base_date,
            )
            session.add(order)
            session.flush()

            max_step = min(len(STATUS_FLOW), index + 3)
            for step_index, status in enumerate(STATUS_FLOW[:max_step]):
                event_at = base_date + timedelta(hours=2 * step_index)
                order.events.append(
                    OrderEvent(
                        status=status,
                        event_at=event_at,
                        note="Демо-данные",
                    )
                )
                order.current_status = status
                order.current_status_at = event_at
            session.add(order)


def seed_demo() -> None:
    init_db()
    _seed_marketplace(Marketplace.WB)
    _seed_marketplace(Marketplace.OZON)
    print("Demo data created.")


if __name__ == "__main__":
    seed_demo()

