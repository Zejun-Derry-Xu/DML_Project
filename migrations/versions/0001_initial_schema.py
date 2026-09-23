"""Create ReturnFlow MVP schema."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "customers",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_customers_email", "customers", ["email"], unique=True)
    op.create_table(
        "orders",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("order_number", sa.String(50), nullable=False),
        sa.Column("customer_id", sa.Uuid(), sa.ForeignKey("customers.id"), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("ordered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_orders_order_number", "orders", ["order_number"], unique=True)
    op.create_index("ix_orders_customer_id", "orders", ["customer_id"])
    op.create_table(
        "order_items",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("order_id", sa.Uuid(), sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("product_name", sa.String(300), nullable=False),
        sa.Column("price", sa.Numeric(10, 2), nullable=False),
        sa.Column("final_sale", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("return_status", sa.String(30)),
    )
    op.create_index("ix_order_items_order_id", "order_items", ["order_id"])
    op.create_table(
        "return_cases",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("customer_id", sa.Uuid(), sa.ForeignKey("customers.id")),
        sa.Column("customer_email", sa.String(320)),
        sa.Column("order_id", sa.Uuid(), sa.ForeignKey("orders.id")),
        sa.Column("order_number", sa.String(50)),
        sa.Column("item_id", sa.Uuid(), sa.ForeignKey("order_items.id")),
        sa.Column("item_name", sa.String(300)),
        sa.Column("reason", sa.String(30)),
        sa.Column("used", sa.Boolean()),
        sa.Column("opened", sa.Boolean()),
        sa.Column("damaged", sa.Boolean()),
        sa.Column("pending_question", sa.String(30)),
        sa.Column("decision", sa.String(40)),
        sa.Column("decision_reason", sa.String(60)),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_return_cases_session_id", "return_cases", ["session_id"], unique=True)
    op.create_table(
        "messages",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_messages_session_id", "messages", ["session_id"])
    op.create_table(
        "question_requests",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("return_case_id", sa.Uuid(), sa.ForeignKey("return_cases.id"), nullable=False),
        sa.Column("field", sa.String(30), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("options", sa.JSON(), nullable=False),
        sa.Column("allow_free_text", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("selected_value", sa.String(200)),
        sa.Column("free_text", sa.Text()),
        sa.Column("case_version", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("answered_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_question_requests_session_id", "question_requests", ["session_id"])
    op.create_index("ix_question_requests_return_case_id", "question_requests", ["return_case_id"])
    op.create_index("ix_question_requests_status", "question_requests", ["status"])
    op.create_table(
        "tool_calls",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("tool_name", sa.String(100), nullable=False),
        sa.Column("arguments", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON()),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(60)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_tool_calls_session_id", "tool_calls", ["session_id"])
    op.create_table(
        "return_requests",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("rma_number", sa.String(40), nullable=False),
        sa.Column("return_case_id", sa.Uuid(), sa.ForeignKey("return_cases.id"), nullable=False),
        sa.Column("order_id", sa.Uuid(), sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("item_id", sa.Uuid(), sa.ForeignKey("order_items.id"), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_return_requests_rma_number", "return_requests", ["rma_number"], unique=True)
    op.create_index(
        "ix_return_requests_return_case_id", "return_requests", ["return_case_id"], unique=True
    )
    op.create_index(
        "ix_return_requests_idempotency_key", "return_requests", ["idempotency_key"], unique=True
    )


def downgrade() -> None:
    for table in [
        "return_requests",
        "tool_calls",
        "question_requests",
        "messages",
        "return_cases",
        "order_items",
        "orders",
        "customers",
    ]:
        op.drop_table(table)
