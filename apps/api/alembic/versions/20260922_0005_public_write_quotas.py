"""Add shared public-write quota counters (only short-lived keyed hashes).

Revision ID: 20260922_0005
Revises: 20260920_0004
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260922_0005"
down_revision: str | None = "20260920_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "public_write_quotas",
        sa.Column("client_key", sa.String(64), primary_key=True),
        sa.Column("route", sa.String(32), primary_key=True),
        sa.Column("window_start", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("attempts BETWEEN 1 AND 1000", name="ck_public_quota_attempts"),
    )
    op.create_index("ix_public_write_quotas_expires_at", "public_write_quotas", ["expires_at"])


def downgrade() -> None:
    # Dropping resets current-hour quotas; retain the additive table on application rollback.
    op.drop_index("ix_public_write_quotas_expires_at", table_name="public_write_quotas")
    op.drop_table("public_write_quotas")
