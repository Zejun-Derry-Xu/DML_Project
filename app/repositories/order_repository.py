from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.models import OrderRecord


class OrderRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def by_number(self, order_number: str) -> OrderRecord | None:
        statement = (
            select(OrderRecord)
            .where(OrderRecord.order_number == order_number.upper())
            .options(selectinload(OrderRecord.customer), selectinload(OrderRecord.items))
        )
        return self.session.scalar(statement)
