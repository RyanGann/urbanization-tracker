"""Add immutable blob identities, private copies and source/run references.

Revision ID: 20260922_0007
Revises: 20260922_0006
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260922_0007"
down_revision: str | None = "20260922_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "artifact_run_seals",
        sa.Column("source_key", sa.String(128), primary_key=True),
        sa.Column("run_id", sa.String(128), primary_key=True),
        sa.Column("required_set_sha256", sa.String(64), nullable=False),
        sa.Column("required_count", sa.Integer(), nullable=False),
        sa.Column(
            "sealed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "length(trim(source_key)) > 0 AND length(trim(run_id)) > 0",
            name="ck_artifact_seal_identity",
        ),
        sa.CheckConstraint(
            "required_set_sha256 ~ '^[0-9a-f]{64}$'", name="ck_artifact_seal_digest"
        ),
        sa.CheckConstraint("required_count BETWEEN 0 AND 1024", name="ck_artifact_seal_count"),
    )
    op.create_table(
        "artifact_blobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("sha256", sa.String(64), nullable=False, unique=True),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="ck_artifact_blob_digest"),
        sa.CheckConstraint("byte_size BETWEEN 0 AND 8589934592", name="ck_artifact_blob_size"),
    )
    op.create_table(
        "artifact_copies",
        sa.Column(
            "blob_id",
            sa.Uuid(),
            sa.ForeignKey("artifact_blobs.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("sink_id", sa.String(64), primary_key=True),
        sa.Column("object_key", sa.String(80), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True)),
        sa.Column("verified_at", sa.DateTime(timezone=True)),
        sa.Column("last_audit_at", sa.DateTime(timezone=True)),
        sa.Column("failure_code", sa.String(48)),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("lease_token", sa.Uuid()),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("multipart_upload_id", sa.String(2048)),
        sa.Column(
            "multipart_parts",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.UniqueConstraint("sink_id", "object_key", name="uq_artifact_copy_destination"),
        sa.CheckConstraint("sink_id ~ '^[0-9a-f]{64}$'", name="ck_artifact_copy_sink"),
        sa.CheckConstraint(
            "object_key ~ '^sha256/[0-9a-f]{2}/[0-9a-f]{2}/[0-9a-f]{64}$'",
            name="ck_artifact_copy_key",
        ),
        sa.CheckConstraint(
            "state IN ('pending','uploaded','verified','failed')", name="ck_artifact_copy_state"
        ),
        sa.CheckConstraint("attempts >= 0", name="ck_artifact_copy_attempts"),
        sa.CheckConstraint(
            "(lease_token IS NULL) = (lease_expires_at IS NULL)", name="ck_artifact_copy_lease"
        ),
        sa.CheckConstraint(
            "state <> 'verified' OR verified_at IS NOT NULL", name="ck_artifact_copy_verified"
        ),
        sa.CheckConstraint(
            "jsonb_typeof(multipart_parts) = 'array' AND "
            "jsonb_array_length(multipart_parts) <= 1024 AND "
            "octet_length(multipart_parts::text) <= 524288",
            name="ck_artifact_copy_checkpoint",
        ),
    )
    op.create_index("ix_artifact_copy_retry", "artifact_copies", ["state", "next_attempt_at"])
    op.create_table(
        "artifact_references",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("source_key", sa.String(128), nullable=False),
        sa.Column("run_id", sa.String(128), nullable=False),
        sa.Column("artifact_type", sa.String(48), nullable=False),
        sa.Column("logical_key", sa.String(256), nullable=False),
        sa.Column(
            "blob_id",
            sa.Uuid(),
            sa.ForeignKey("artifact_blobs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("required", sa.Boolean(), nullable=False),
        sa.Column("content_type", sa.String(128)),
        sa.Column("source_url", sa.Text()),
        sa.Column(
            "parent_reference_id",
            sa.Uuid(),
            sa.ForeignKey("artifact_references.id", ondelete="RESTRICT"),
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint(
            "source_key",
            "run_id",
            "artifact_type",
            "logical_key",
            name="uq_artifact_reference_observation",
        ),
        sa.CheckConstraint(
            "length(trim(source_key)) > 0 AND length(trim(run_id)) > 0 AND "
            "length(trim(artifact_type)) > 0 AND length(trim(logical_key)) > 0",
            name="ck_artifact_reference_identity",
        ),
        sa.CheckConstraint("parent_reference_id <> id", name="ck_artifact_reference_parent"),
    )
    op.create_index("ix_artifact_reference_run", "artifact_references", ["source_key", "run_id"])


def downgrade() -> None:
    raise RuntimeError(
        "Artifact provenance and upload checkpoints must be retained. "
        "Roll back application code while retaining the additive artifact schema."
    )
