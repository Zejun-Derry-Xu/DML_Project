from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import NAMESPACE_URL, uuid5

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import CustomerRecord, OrderItemRecord, OrderRecord
from app.db.session import Base, get_db
from app.main import create_app


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    local_session = sessionmaker(bind=engine, expire_on_commit=False)
    with local_session() as session:
        seed_test_orders(session)
        yield session
    Base.metadata.drop_all(engine)


@pytest.fixture
def client(db_session: Session) -> Generator[TestClient, None, None]:
    app = create_app()

    def override_db():
        yield db_session

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as test_client:
        yield test_client


def seed_test_orders(session: Session) -> None:
    now = datetime.now(UTC)
    customer = CustomerRecord(
        id=uuid5(NAMESPACE_URL, "test-customer"),
        email="june@example.com",
        name="June Park",
    )
    session.add(customer)
    eligible = OrderRecord(
        id=uuid5(NAMESPACE_URL, "eligible-order"),
        order_number="ORD-1010",
        customer_id=customer.id,
        status="delivered",
        ordered_at=now - timedelta(days=6),
        delivered_at=now - timedelta(days=2),
    )
    final_sale = OrderRecord(
        id=uuid5(NAMESPACE_URL, "final-sale-order"),
        order_number="ORD-1004",
        customer_id=customer.id,
        status="delivered",
        ordered_at=now - timedelta(days=6),
        delivered_at=now - timedelta(days=2),
    )
    multi = OrderRecord(
        id=uuid5(NAMESPACE_URL, "multi-order"),
        order_number="ORD-1005",
        customer_id=customer.id,
        status="delivered",
        ordered_at=now - timedelta(days=6),
        delivered_at=now - timedelta(days=2),
    )
    session.add_all([eligible, final_sale, multi])
    session.flush()
    session.add_all(
        [
            OrderItemRecord(
                id=uuid5(NAMESPACE_URL, "eligible-item"),
                order_id=eligible.id,
                product_name="Linen Shirt",
                price=Decimal("55.00"),
                final_sale=False,
            ),
            OrderItemRecord(
                id=uuid5(NAMESPACE_URL, "final-sale-item"),
                order_id=final_sale.id,
                product_name="Clearance Jacket",
                price=Decimal("49.00"),
                final_sale=True,
            ),
            OrderItemRecord(
                id=uuid5(NAMESPACE_URL, "multi-item-1"),
                order_id=multi.id,
                product_name="Headphones",
                price=Decimal("199.00"),
                final_sale=False,
            ),
            OrderItemRecord(
                id=uuid5(NAMESPACE_URL, "multi-item-2"),
                order_id=multi.id,
                product_name="Cable",
                price=Decimal("14.99"),
                final_sale=False,
            ),
        ]
    )
    session.commit()
