from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.schemas import OrderResponse
from app.db.session import get_db
from app.domain.models import OrderSnapshot
from app.repositories.order_repository import OrderRepository
from app.services.order_service import OrderService

router = APIRouter(prefix="/orders", tags=["orders"])


@router.get("/{order_number}", response_model=OrderResponse)
def get_order(
    order_number: str, email: str = Query(...), db: Session = Depends(get_db)
) -> OrderSnapshot:
    return OrderService(OrderRepository(db)).lookup(order_number, email)
