"""Add resumable, immutable projected environmental display derivatives.

Revision ID: 20260924_0008
Revises: 20260922_0007
"""

from collections.abc import Sequence

import sqlalchemy as sa
from geoalchemy2 import Geometry

from alembic import op

revision: str = "20260924_0008"
down_revision: str | None = "20260922_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "environmental_display_builds",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("environmental_layer_id", sa.Integer(), nullable=False),
        sa.Column("layer_key", sa.String(100), nullable=False),
        sa.Column("data_version", sa.String(64), nullable=False),
        sa.Column("source_checksum", sa.String(64), nullable=False),
        sa.Column("source_snapshot_sha256", sa.String(64), nullable=False),
        sa.Column("display_version", sa.String(64), nullable=False),
        sa.Column("config_sha256", sa.String(64), nullable=False),
        sa.Column("config_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("summary_json", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(
            ["environmental_layer_id"], ["environmental_layers.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint(
            "environmental_layer_id", "display_version", name="uq_environmental_display_build"
        ),
        sa.CheckConstraint(
            "status IN ('building', 'validated', 'failed')",
            name="ck_environmental_display_build_status",
        ),
    )
    op.create_table(
        "environmental_display_bands",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("build_id", sa.Integer(), nullable=False),
        sa.Column("band_key", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("checkpoint_feature_id", sa.Integer(), nullable=False),
        sa.Column("processed_count", sa.Integer(), nullable=False),
        sa.Column("part_count", sa.Integer(), nullable=False),
        sa.Column("collapsed_count", sa.Integer(), nullable=False),
        sa.Column("invalid_count", sa.Integer(), nullable=False),
        sa.Column("diagnostics_json", sa.JSON(), nullable=False),
        sa.Column("checkpoint_sha256", sa.String(64)),
        sa.Column("parts_sha256", sa.String(64)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["build_id"], ["environmental_display_builds.id"],
                                ondelete="RESTRICT"),
        sa.UniqueConstraint("build_id", "band_key", name="uq_environmental_display_band"),
        sa.CheckConstraint(
            "status IN ('building', 'validated', 'failed')",
            name="ck_environmental_display_band_status",
        ),
        sa.CheckConstraint(
            "checkpoint_feature_id >= 0 AND processed_count >= 0 AND part_count >= 0 "
            "AND collapsed_count >= 0 AND invalid_count >= 0",
            name="ck_environmental_display_band_counts",
        ),
    )
    op.create_table(
        "environmental_display_feature_results",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("build_id", sa.Integer(), nullable=False),
        sa.Column("environmental_feature_id", sa.Integer(), nullable=False),
        sa.Column("band_key", sa.String(16), nullable=False),
        sa.Column("source_feature_id", sa.String(255), nullable=False),
        sa.Column("input_fingerprint", sa.String(64), nullable=False),
        sa.Column("input_geometry_sha256", sa.String(64), nullable=False),
        sa.Column("simplified_geometry_sha256", sa.String(64), nullable=False),
        sa.Column("output_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("error_code", sa.String(80)),
        sa.Column("part_count", sa.Integer(), nullable=False),
        sa.Column("source_holes", sa.Integer(), nullable=False),
        sa.Column("display_holes", sa.Integer(), nullable=False),
        sa.Column("source_components", sa.Integer(), nullable=False),
        sa.Column("display_components", sa.Integer(), nullable=False),
        sa.Column("collapsed", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["build_id"], ["environmental_display_builds.id"],
                                ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["environmental_feature_id"], ["environmental_features.id"],
                                ondelete="RESTRICT"),
        sa.UniqueConstraint(
            "build_id", "band_key", "environmental_feature_id",
            name="uq_environmental_display_feature_result",
        ),
        sa.CheckConstraint(
            "status IN ('built', 'collapsed', 'failed')",
            name="ck_environmental_display_feature_status",
        ),
    )
    op.create_table(
        "environmental_display_parts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("build_id", sa.Integer(), nullable=False),
        sa.Column("environmental_feature_id", sa.Integer(), nullable=False),
        sa.Column("band_key", sa.String(16), nullable=False),
        sa.Column("source_feature_id", sa.String(255), nullable=False),
        sa.Column("part_number", sa.Integer(), nullable=False),
        sa.Column("geometry_sha256", sa.String(64), nullable=False),
        sa.Column("geometry", Geometry("POLYGON", srid=3857, spatial_index=False),
                  nullable=False),
        sa.ForeignKeyConstraint(["build_id"], ["environmental_display_builds.id"],
                                ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["environmental_feature_id"], ["environmental_features.id"],
                                ondelete="RESTRICT"),
        sa.UniqueConstraint(
            "build_id", "band_key", "environmental_feature_id", "part_number",
            name="uq_environmental_display_part",
        ),
        sa.CheckConstraint("part_number >= 0", name="ck_environmental_display_part_number"),
    )
    op.create_index(
        "ix_environmental_display_parts_build_band", "environmental_display_parts",
        ["build_id", "band_key"],
    )
    op.create_index(
        "ix_environmental_display_parts_geometry", "environmental_display_parts",
        ["geometry"], postgresql_using="gist",
    )


def downgrade() -> None:
    raise RuntimeError(
        "Retain P04a additive display schema on application rollback; downgrade "
        "would destroy immutable build/checkpoint evidence"
    )
