"""Add nullable apparel facts; preserve historical decisions and explicit catalog identity."""

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str = "0002"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column(
        "order_items",
        sa.Column("category", sa.String(20), server_default="general", nullable=False),
    )
    for field in ("stained", "tags_attached", "tags_intact"):
        op.add_column("return_cases", sa.Column(field, sa.Boolean(), nullable=True))
    op.add_column("return_cases", sa.Column("condition_origin", sa.String(20), nullable=True))
    op.add_column(
        "return_cases",
        sa.Column("policy_version", sa.String(30), server_default="mvp-1.0.0", nullable=False),
    )
    # These are explicit seeded catalog IDs, not an LLM/name-based classifier.
    from scripts.seed_data import stable_id

    table = sa.table("order_items", sa.column("id", sa.Uuid()), sa.column("category", sa.String()))
    for order in ("ORD-1004", "ORD-1010"):
        op.execute(
            table.update()
            .where(table.c.id == stable_id("item", f"{order}:0"))
            .values(category="apparel")
        )
    # Existing rows retain v1; application creation explicitly uses v2.
    with op.batch_alter_table("return_cases") as batch:
        batch.alter_column(
            "policy_version", existing_type=sa.String(30), server_default="mvp-2.0.0"
        )


def downgrade() -> None:
    raise RuntimeError(
        "Destructive downgrade disabled: restore a verified backup only with explicit approval."
    )
