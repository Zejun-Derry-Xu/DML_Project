from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.schemas import OrderResponse
from app.config import get_settings
from app.db.models import CustomerRecord
from app.db.session import get_db
from app.domain.models import OrderSnapshot
from app.repositories.order_repository import OrderRepository
from app.services.apparel_service import ApparelService
from app.services.demo_identity import current_demo_customer, optional_demo_customer
from app.services.order_service import OrderService

router = APIRouter(prefix="/orders", tags=["orders"])


@router.get("")
def list_orders(
    customer: CustomerRecord = Depends(current_demo_customer), db: Session = Depends(get_db)
) -> list[dict[str, Any]]:
    return ApparelService(db, customer, get_settings()).list_orders()


@router.get("/{order_number}", response_model=OrderResponse)
def get_order(
    order_number: str,
    email: str = Query(default=""),
    db: Session = Depends(get_db),
    customer: CustomerRecord | None = Depends(optional_demo_customer),
) -> OrderSnapshot:
    if get_settings().workflow_mode == "apparel":
        assert customer is not None
        order = ApparelService(db, customer, get_settings())._order(order_number)
        return OrderService(OrderRepository(db)).lookup(order.order_number, customer.email)
    return OrderService(OrderRepository(db)).lookup(order_number, email)
