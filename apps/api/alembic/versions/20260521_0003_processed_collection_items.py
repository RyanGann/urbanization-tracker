"""Add durable processed ingestion collection store.

Revision ID: 20260521_0003
Revises: 20260520_0002
Create Date: 2026-05-21
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260521_0003"
down_revision: str | None = "20260520_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "processed_collection_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("collection_name", sa.String(length=120), nullable=False),
        sa.Column("item_id", sa.String(length=255), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("collection_name", "item_id", name="uq_processed_collection_item"),
    )
    op.create_index(
        "ix_processed_collection_items_collection_name",
        "processed_collection_items",
        ["collection_name"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_processed_collection_items_collection_name",
        table_name="processed_collection_items",
    )
    op.drop_table("processed_collection_items")
