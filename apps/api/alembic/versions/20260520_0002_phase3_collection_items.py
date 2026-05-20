"""Add durable Phase 3 collection store.

Revision ID: 20260520_0002
Revises: 20260520_0001
Create Date: 2026-05-20
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260520_0002"
down_revision: str | None = "20260520_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "phase3_collection_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("collection_name", sa.String(length=120), nullable=False),
        sa.Column("item_id", sa.String(length=255), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("collection_name", "item_id", name="uq_phase3_collection_item"),
    )
    op.create_index(
        "ix_phase3_collection_items_collection_name",
        "phase3_collection_items",
        ["collection_name"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_phase3_collection_items_collection_name",
        table_name="phase3_collection_items",
    )
    op.drop_table("phase3_collection_items")
