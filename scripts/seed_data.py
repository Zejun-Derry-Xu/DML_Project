import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select

from app.db.models import CustomerRecord, OrderItemRecord, OrderRecord
from app.db.session import SessionLocal

DATA_FILE = Path(__file__).parents[1] / "data" / "seed_orders.json"


def stable_id(kind: str, value: str):
    return uuid5(NAMESPACE_URL, f"returnflow:{kind}:{value}")


def seed() -> None:
    records = json.loads(DATA_FILE.read_text())
    now = datetime.now(UTC)
    with SessionLocal.begin() as session:
        for data in records:
            existing = session.scalar(
                select(OrderRecord).where(OrderRecord.order_number == data["order_number"])
            )
            if existing:
                continue
            customer = session.scalar(
                select(CustomerRecord).where(CustomerRecord.email == data["email"])
            )
            if customer is None:
                customer = CustomerRecord(
                    id=stable_id("customer", data["email"]),
                    email=data["email"],
                    name=data["name"],
                )
                session.add(customer)
                session.flush()
            order = OrderRecord(
                id=stable_id("order", data["order_number"]),
                order_number=data["order_number"],
                customer_id=customer.id,
                status=data["status"],
                ordered_at=now - timedelta(days=data["ordered_days_ago"]),
                delivered_at=(
                    None
                    if data["delivered_days_ago"] is None
                    else now - timedelta(days=data["delivered_days_ago"])
                ),
            )
            session.add(order)
            for index, item in enumerate(data["items"]):
                session.add(
                    OrderItemRecord(
                        id=stable_id("item", f"{data['order_number']}:{index}"),
                        order_id=order.id,
                        product_name=item["product_name"],
                        price=Decimal(item["price"]),
                        final_sale=item["final_sale"],
                        return_status=item.get("return_status"),
                    )
                )


if __name__ == "__main__":
    seed()
