"""Add source identity registry and scope-aware ingestion batches.

Revision ID: 20260920_0004
Revises: 20260521_0003
Create Date: 2026-09-20
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260920_0004"
down_revision: str | None = "20260521_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "source_identity_registry",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_key", sa.String(length=120), nullable=False),
        sa.Column("source_record_id", sa.String(length=255), nullable=False),
        sa.Column("public_id", sa.String(length=255), nullable=False),
        sa.Column("first_discovered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_key", "source_record_id", name="uq_source_identity_anchor"),
    )
    op.create_index("ix_source_identity_registry_source_key", "source_identity_registry", ["source_key"])
    op.create_index("ix_source_identity_registry_public_id", "source_identity_registry", ["public_id"])
    op.create_table(
        "source_ingestion_batches",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.String(length=255), nullable=False),
        sa.Column("source_key", sa.String(length=120), nullable=False),
        sa.Column("scope_id", sa.String(length=255), nullable=False),
        sa.Column("scope_version", sa.String(length=255), nullable=False),
        sa.Column("coverage", sa.String(length=20), nullable=False),
        sa.Column("outcome", sa.String(length=20), nullable=False),
        sa.Column("counts_json", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "source_key", "scope_id", "scope_version", name="uq_source_ingestion_batch_replay"),
    )
    op.create_index("ix_source_ingestion_batches_source_key", "source_ingestion_batches", ["source_key"])
    op.create_table(
        "source_observations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("batch_id", sa.Integer(), nullable=False),
        sa.Column("registry_id", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("content_fingerprint", sa.String(length=128), nullable=True),
        sa.Column("fingerprint_version", sa.String(length=40), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["batch_id"], ["source_ingestion_batches.id"]),
        sa.ForeignKeyConstraint(["registry_id"], ["source_identity_registry.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("batch_id", "registry_id", name="uq_source_observation_batch_registry"),
    )
    op.create_index("ix_source_observations_batch_id", "source_observations", ["batch_id"])
    op.create_index("ix_source_observations_registry_id", "source_observations", ["registry_id"])


def downgrade() -> None:
    op.drop_index("ix_source_observations_registry_id", table_name="source_observations")
    op.drop_index("ix_source_observations_batch_id", table_name="source_observations")
    op.drop_table("source_observations")
    op.drop_index("ix_source_ingestion_batches_source_key", table_name="source_ingestion_batches")
    op.drop_table("source_ingestion_batches")
    op.drop_index("ix_source_identity_registry_public_id", table_name="source_identity_registry")
    op.drop_index("ix_source_identity_registry_source_key", table_name="source_identity_registry")
    op.drop_table("source_identity_registry")
