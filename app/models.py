from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.enums import Marketplace, OrderStatus


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        Index("ix_orders_marketplace", "marketplace"),
        Index("ix_orders_current_status", "current_status"),
        Index("ix_orders_external_order_id", "external_order_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    marketplace: Mapped[Marketplace] = mapped_column(SAEnum(Marketplace), nullable=False)
    external_order_id: Mapped[str] = mapped_column(String(128), nullable=False)
    product_name: Mapped[str] = mapped_column(String(256), nullable=False)
    sku: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    quantity: Mapped[int] = mapped_column(default=1, nullable=False)
    due_ship_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    current_status: Mapped[OrderStatus] = mapped_column(SAEnum(OrderStatus), nullable=False)
    current_status_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    comment: Mapped[Optional[str]] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    events: Mapped[list["OrderEvent"]] = relationship(
        "OrderEvent",
        back_populates="order",
        cascade="all, delete-orphan",
        order_by="OrderEvent.event_at",
    )


class OrderEvent(Base):
    __tablename__ = "order_events"
    __table_args__ = (
        Index("ix_order_events_order_id", "order_id"),
        Index("ix_order_events_status", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[OrderStatus] = mapped_column(SAEnum(OrderStatus), nullable=False)
    event_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    note: Mapped[Optional[str]] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    order: Mapped[Order] = relationship("Order", back_populates="events")

