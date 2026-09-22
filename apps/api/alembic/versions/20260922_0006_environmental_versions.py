"""Add immutable environmental import versions without rewriting legacy features.

Revision ID: 20260922_0006
Revises: 20260922_0005
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260922_0006"
down_revision: str | None = "20260922_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    columns = [
        sa.Column("layer_key", sa.String(100)),
        sa.Column("data_version", sa.String(64)),
        sa.Column("source_checksum", sa.String(64)),
        sa.Column("importer_format", sa.String(32)),
        sa.Column("scope_json", sa.JSON()),
        sa.Column("import_status", sa.String(16)),
        sa.Column("coverage_status", sa.String(16)),
        sa.Column("expected_count", sa.Integer()),
        sa.Column("seen_count", sa.Integer()),
        sa.Column("accepted_count", sa.Integer()),
        sa.Column("rejected_count", sa.Integer()),
        sa.Column("duplicate_count", sa.Integer()),
        sa.Column("import_checkpoint", sa.Integer()),
        sa.Column("bounds_json", sa.JSON()),
        sa.Column("diagnostics_json", sa.JSON()),
        sa.Column("import_started_at", sa.DateTime(timezone=True)),
        sa.Column("import_finished_at", sa.DateTime(timezone=True)),
    ]
    for column in columns:
        op.add_column("environmental_layers", column)
    op.create_unique_constraint(
        "uq_environmental_layer_version", "environmental_layers", ["layer_key", "data_version"]
    )
    op.create_check_constraint(
        "ck_environmental_layer_version_pair",
        "environmental_layers",
        "(layer_key IS NULL) = (data_version IS NULL)",
    )
    op.create_check_constraint(
        "ck_environmental_import_status",
        "environmental_layers",
        "import_status IS NULL OR import_status IN ('loading', 'validated', 'failed')",
    )
    op.add_column(
        "environmental_features",
        sa.Column(
            "import_managed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column("environmental_features", sa.Column("import_fingerprint", sa.String(64)))
    op.create_check_constraint(
        "ck_environmental_managed_feature_identity",
        "environmental_features",
        "NOT import_managed OR (source_feature_id IS NOT NULL AND btrim(source_feature_id) <> '')",
    )
    # Legacy duplicate source IDs remain untouched and outside the new constraint.
    op.create_index(
        "uq_environmental_managed_feature",
        "environmental_features",
        ["environmental_layer_id", "source_feature_id"],
        unique=True,
        postgresql_where=sa.text("import_managed IS TRUE"),
    )
    # Geometry already has a GeoAlchemy GiST index; do not add a duplicate.


def downgrade() -> None:
    # Application rollback must retain this additive schema and imported versions.
    # Downgrading would destroy identity/provenance and make immutable rows ambiguous.
    raise RuntimeError(
        "Retain P03 additive schema on rollback; downgrade would lose import history"
    )
