"""Prevent cross-session duplicate returns for the same order item."""

from alembic import op

revision: str = "0002"
down_revision: str = "0001"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    # Existing duplicates intentionally fail this migration; never delete history silently.
    op.create_index("ix_return_requests_item_id", "return_requests", ["item_id"], unique=True)
    op.execute(
        "UPDATE order_items SET return_status = 'requested' "
        "WHERE return_status IS NULL AND id IN (SELECT item_id FROM return_requests)"
    )


def downgrade() -> None:
    op.drop_index("ix_return_requests_item_id", table_name="return_requests")
