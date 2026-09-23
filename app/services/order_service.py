from uuid import UUID

from app.db.models import OrderRecord
from app.domain.models import OrderItem, OrderSnapshot
from app.errors import AppError
from app.repositories.order_repository import OrderRepository


def to_snapshot(order: OrderRecord) -> OrderSnapshot:
    return OrderSnapshot(
        id=order.id,
        order_number=order.order_number,
        customer_email=order.customer.email,
        status=order.status,
        ordered_at=order.ordered_at,
        delivered_at=order.delivered_at,
        items=[
            OrderItem(
                id=item.id,
                product_name=item.product_name,
                price=item.price,
                final_sale=item.final_sale,
                return_status=item.return_status,
            )
            for item in order.items
        ],
    )


class OrderService:
    def __init__(self, repository: OrderRepository) -> None:
        self.repository = repository

    def lookup(self, order_number: str, email: str) -> OrderSnapshot:
        order = self.repository.by_number(order_number)
        if order is None:
            raise AppError("ORDER_NOT_FOUND", "The requested order could not be found.", 404)
        if order.customer.email.casefold() != email.casefold():
            raise AppError(
                "IDENTITY_MISMATCH",
                "The order does not match the supplied customer email.",
                403,
            )
        return to_snapshot(order)

    @staticmethod
    def select_item(order: OrderSnapshot, item_id: UUID | None) -> OrderItem:
        if item_id is None and len(order.items) == 1:
            return order.items[0]
        for item in order.items:
            if item.id == item_id:
                return item
        raise AppError("ITEM_NOT_FOUND", "The selected item is not part of this order.", 404)
