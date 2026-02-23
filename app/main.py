from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_session, init_db
from app.enums import Marketplace, OrderStatus
from app.schemas import (
    DashboardSummary,
    OrderCreate,
    OrderEventCreate,
    OrderRead,
    OrdersResponse,
    StatusCatalogItem,
)
from app.services import (
    add_order_event,
    build_summary,
    create_order,
    get_order_or_404,
    list_orders,
    marketplace_catalog,
    status_catalog,
)

app = FastAPI(title=settings.app_name, version="0.1.0")
static_dir = Path(__file__).resolve().parent / "static"

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.on_event("startup")
def startup_event() -> None:
    init_db()


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


@app.post("/api/orders", response_model=OrderRead, status_code=201)
def create_order_endpoint(payload: OrderCreate, session: Session = Depends(get_session)) -> OrderRead:
    order = create_order(session, payload)
    return get_order_or_404(session, order.id)


@app.get("/api/orders", response_model=OrdersResponse)
def list_orders_endpoint(
    marketplace: Optional[Marketplace] = Query(default=None),
    status: Optional[OrderStatus] = Query(default=None),
    search: Optional[str] = Query(default=None, max_length=128),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> OrdersResponse:
    items, total = list_orders(
        session=session,
        marketplace=marketplace,
        status=status,
        search=search,
        limit=limit,
        offset=offset,
    )
    return OrdersResponse(items=items, total=total)


@app.get("/api/orders/{order_id}", response_model=OrderRead)
def get_order_endpoint(order_id: int, session: Session = Depends(get_session)) -> OrderRead:
    try:
        return get_order_or_404(session, order_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/orders/{order_id}/events", response_model=OrderRead)
def add_event_endpoint(
    order_id: int,
    payload: OrderEventCreate,
    session: Session = Depends(get_session),
) -> OrderRead:
    try:
        order = get_order_or_404(session, order_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return add_order_event(session, order, payload)


@app.get("/api/dashboard/{marketplace}", response_model=DashboardSummary)
def dashboard_marketplace_endpoint(
    marketplace: Marketplace, session: Session = Depends(get_session)
) -> DashboardSummary:
    return build_summary(session, marketplace)


@app.get("/api/dashboard")
def dashboard_all_endpoint(session: Session = Depends(get_session)) -> list[DashboardSummary]:
    return [build_summary(session, marketplace) for marketplace in Marketplace]

