"""Expand only: demo identity, observations and durable simulated support tickets."""

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "customers", sa.Column("is_demo", sa.Boolean(), server_default="0", nullable=False)
    )
    op.add_column(
        "return_cases",
        sa.Column("workflow_version", sa.String(30), server_default="legacy", nullable=False),
    )
    op.add_column("return_cases", sa.Column("reason_text", sa.Text(), nullable=True))
    op.add_column(
        "return_cases",
        sa.Column("field_observations", sa.JSON(), server_default="{}", nullable=False),
    )
    op.create_table(
        "support_tickets",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("return_case_id", sa.Uuid(), sa.ForeignKey("return_cases.id"), nullable=False),
        sa.Column("customer_id", sa.Uuid(), sa.ForeignKey("customers.id"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index(
        "ix_support_tickets_return_case_id", "support_tickets", ["return_case_id"], unique=True
    )
    op.create_index("ix_support_tickets_customer_id", "support_tickets", ["customer_id"])


def downgrade() -> None:
    raise RuntimeError(
        "Destructive downgrade disabled; use a compatible image, never delete records."
    )
