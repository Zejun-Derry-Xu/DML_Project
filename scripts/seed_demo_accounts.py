"""Explicit, idempotent fictional seed; never reset dates or consumed existing orders."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.db.models import CustomerRecord, OrderItemRecord, OrderRecord
from app.db.session import SessionLocal
from scripts.seed_data import stable_id


def seed_demo(session: Session) -> None:
    now = datetime.now(UTC)
    for key, name in (("alice", "Alice (fictional)"), ("bob", "Bob (fictional)")):
        customer_id = stable_id("demo-customer", key)
        if session.get(CustomerRecord, customer_id) is None:
            session.add(
                CustomerRecord(
                    id=customer_id, email=f"demo-{key}@example.invalid", name=name, is_demo=True
                )
            )
    session.flush()
    for number, owner, days, final, category, status in (
        ("DEMO-1001", "alice", 2, False, "apparel", "delivered"),
        ("DEMO-1002", "alice", 40, False, "apparel", "delivered"),
        ("DEMO-1003", "alice", 2, True, "apparel", "delivered"),
        ("DEMO-1004", "alice", 2, False, "general", "delivered"),
        ("DEMO-1005", "alice", 0, False, "apparel", "shipped"),
        ("DEMO-2001", "bob", 3, False, "apparel", "delivered"),
    ):
        order_id = stable_id("demo-order", number)
        if session.get(OrderRecord, order_id):
            continue
        session.add(
            OrderRecord(
                id=order_id,
                order_number=number,
                customer_id=stable_id("demo-customer", owner),
                status=status,
                ordered_at=now - timedelta(days=days + 3),
                delivered_at=now - timedelta(days=days) if status == "delivered" else None,
            )
        )
        session.flush()
        session.add(
            OrderItemRecord(
                id=stable_id("demo-item", number),
                order_id=order_id,
                product_name="Demo linen shirt" if category == "apparel" else "Demo cable",
                category=category,
                price=Decimal("45.00"),
                final_sale=final,
            )
        )
    session.flush()


if __name__ == "__main__":
    with SessionLocal.begin() as db:
        seed_demo(db)
