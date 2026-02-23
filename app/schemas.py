from datetime import datetime

from pydantic import BaseModel, Field

from app.enums import Marketplace, OrderStatus


class OrderEventRead(BaseModel):
    id: int
    status: OrderStatus
    status_name: str
    event_at: datetime
    note: str | None = None


class OrderRead(BaseModel):
    id: int
    marketplace: Marketplace
    marketplace_name: str
    assembly_task_number: str
    product_name: str
    sku: str | None
    quantity: int
    current_status: OrderStatus
    current_status_name: str
    current_status_at: datetime
    created_at: datetime
    updated_at: datetime
    events: list[OrderEventRead] = Field(default_factory=list)


class OrderBrief(BaseModel):
    assembly_task_number: str
    current_status: OrderStatus
    current_status_name: str
    current_status_at: datetime


class OrdersResponse(BaseModel):
    items: list[OrderRead]
    total: int


class DashboardSummary(BaseModel):
    marketplace: Marketplace
    marketplace_name: str
    total_orders: int
    updated_today: int
    by_status: dict[str, int]


class StatusCatalogItem(BaseModel):
    code: str
    name: str


class SettingsRead(BaseModel):
    wb_token: str
    ozon_client_id: str
    ozon_api_key: str
    updated_at: datetime | None = None


class SettingsUpdate(BaseModel):
    wb_token: str = Field(default="", max_length=512)
    ozon_client_id: str = Field(default="", max_length=128)
    ozon_api_key: str = Field(default="", max_length=512)


class SyncReport(BaseModel):
    wb_received: int
    ozon_received: int
    processed_orders: int
    created_orders: int
    updated_orders: int
    created_events: int
    message: str


class TodaySummary(BaseModel):
    date: str
    wb_updates: int
    ozon_updates: int
    total_updates: int

