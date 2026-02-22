from datetime import datetime, timedelta, timezone
from random import randint

from sqlalchemy import select

from app.db import init_db, session_scope
from app.enums import Marketplace, OrderStatus
from app.models import Order
from app.schemas import OrderCreate, OrderEventCreate
from app.services import add_order_event, create_order, get_order_or_404


def _seed_marketplace(marketplace: Marketplace) -> None:
    now = datetime.now(timezone.utc)
    titles = [
        ("Лосины женские S", "WB-784"),
        ("Рюкзак городской 22л", "WB-912"),
        ("Термос 500мл", "WB-445"),
    ]
    status_flow = [
        OrderStatus.ASSEMBLY,
        OrderStatus.WAREHOUSE_HANDOVER,
        OrderStatus.SORTED,
        OrderStatus.IN_TRANSIT_TO_BUYER_PICKUP,
        OrderStatus.ARRIVED_AT_BUYER_PICKUP,
        OrderStatus.BUYOUT,
    ]

    with session_scope() as session:
        existing = session.scalar(select(Order.id).where(Order.marketplace == marketplace))
        if existing:
            return

        for index, (name, sku) in enumerate(titles, start=1):
            base_date = now - timedelta(days=randint(1, 7))
            created = create_order(
                session,
                OrderCreate(
                    marketplace=marketplace,
                    external_order_id=f"{marketplace.value.upper()}-{index:04d}",
                    product_name=name,
                    sku=sku if marketplace == Marketplace.WB else sku.replace("WB", "OZ"),
                    quantity=randint(1, 3),
                    due_ship_at=base_date + timedelta(hours=8),
                    initial_status=OrderStatus.ASSEMBLY,
                    initial_status_at=base_date,
                ),
            )
            order = get_order_or_404(session, created.id)
            for step in status_flow[1 : index + 2]:
                add_order_event(
                    session,
                    order,
                    OrderEventCreate(
                        status=step,
                        event_at=base_date + timedelta(hours=2 * status_flow.index(step)),
                        note=None,
                    ),
                )


def seed_demo() -> None:
    init_db()
    _seed_marketplace(Marketplace.WB)
    _seed_marketplace(Marketplace.OZON)
    print("Demo data created.")


if __name__ == "__main__":
    seed_demo()

