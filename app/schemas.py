from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.enums import Marketplace, OrderStatus


class OrderEventCreate(BaseModel):
    status: OrderStatus
    event_at: datetime
    note: Optional[str] = Field(default=None, max_length=2000)


class OrderCreate(BaseModel):
    marketplace: Marketplace
    external_order_id: str = Field(min_length=1, max_length=128)
    product_name: str = Field(min_length=1, max_length=256)
    sku: Optional[str] = Field(default=None, max_length=128)
    quantity: int = Field(default=1, ge=1, le=9999)
    due_ship_at: Optional[datetime] = None
    comment: Optional[str] = Field(default=None, max_length=2000)
    initial_status: OrderStatus = OrderStatus.ASSEMBLY
    initial_status_at: Optional[datetime] = None


class OrderEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: OrderStatus
    event_at: datetime
    note: Optional[str] = None


class OrderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    marketplace: Marketplace
    external_order_id: str
    product_name: str
    sku: Optional[str]
    quantity: int
    due_ship_at: Optional[datetime]
    current_status: OrderStatus
    current_status_at: datetime
    comment: Optional[str]
    created_at: datetime
    updated_at: datetime
    events: list[OrderEventRead] = []


class OrdersResponse(BaseModel):
    items: list[OrderRead]
    total: int


class DashboardSummary(BaseModel):
    marketplace: Marketplace
    total_orders: int
    active_orders: int
    overdue_to_ship: int
    buyout_count: int
    rejection_count: int
    return_count: int
    defect_count: int
    buyout_rate_percent: float
    by_status: dict[str, int]


class StatusCatalogItem(BaseModel):
    code: str
    name: str

