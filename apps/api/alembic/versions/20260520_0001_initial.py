"""Initial PostGIS data model.

Revision ID: 20260520_0001
Revises:
Create Date: 2026-05-20
"""

from collections.abc import Sequence

import geoalchemy2
import sqlalchemy as sa

from alembic import op

revision: str = "20260520_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")

    op.create_table(
        "agencies",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("jurisdiction_name", sa.String(length=255), nullable=True),
        sa.Column("jurisdiction_type", sa.String(length=100), nullable=True),
        sa.Column("website_url", sa.Text(), nullable=True),
        sa.Column("contact_url", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "data_sources",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("agency_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("source_type", sa.String(length=100), nullable=False),
        sa.Column("base_url", sa.Text(), nullable=False),
        sa.Column("license_notes", sa.Text(), nullable=True),
        sa.Column("attribution", sa.Text(), nullable=True),
        sa.Column("update_cadence", sa.String(length=100), nullable=True),
        sa.Column("connector_key", sa.String(length=255), nullable=True),
        sa.Column("connector_config_json", sa.JSON(), nullable=True),
        sa.Column("health_status", sa.String(length=50), nullable=False),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["agency_id"], ["agencies.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "ingestion_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("data_source_id", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("records_seen", sa.Integer(), nullable=False),
        sa.Column("records_created", sa.Integer(), nullable=False),
        sa.Column("records_updated", sa.Integer(), nullable=False),
        sa.Column("records_skipped", sa.Integer(), nullable=False),
        sa.Column("error_count", sa.Integer(), nullable=False),
        sa.Column("log_uri", sa.Text(), nullable=True),
        sa.Column("source_window_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_window_end", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["data_source_id"], ["data_sources.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "source_documents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("data_source_id", sa.Integer(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("document_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("content_type", sa.String(length=255), nullable=True),
        sa.Column("storage_uri", sa.Text(), nullable=True),
        sa.Column("extracted_text", sa.Text(), nullable=True),
        sa.Column("extraction_status", sa.String(length=50), nullable=True),
        sa.ForeignKeyConstraint(["data_source_id"], ["data_sources.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "raw_records",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("data_source_id", sa.Integer(), nullable=False),
        sa.Column("ingestion_run_id", sa.Integer(), nullable=True),
        sa.Column("source_record_id", sa.String(length=255), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("payload_sha256", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(["data_source_id"], ["data_sources.id"]),
        sa.ForeignKeyConstraint(["ingestion_run_id"], ["ingestion_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "staged_development_records",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("raw_record_id", sa.Integer(), nullable=True),
        sa.Column("source_document_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("development_type", sa.String(length=100), nullable=True),
        sa.Column("source_status", sa.String(length=100), nullable=True),
        sa.Column("normalized_status", sa.String(length=100), nullable=True),
        sa.Column("application_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approval_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("permit_issue_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("date_discovered", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("date_last_checked", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("source_agency", sa.String(length=255), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("parcel_ids", sa.JSON(), nullable=True),
        sa.Column(
            "geometry",
            geoalchemy2.types.Geometry(geometry_type="GEOMETRY", srid=4326),
            nullable=True,
        ),
        sa.Column("geometry_source", sa.String(length=255), nullable=True),
        sa.Column("geometry_confidence", sa.String(length=50), nullable=True),
        sa.Column("record_confidence", sa.String(length=50), nullable=True),
        sa.Column("review_status", sa.String(length=50), nullable=False),
        sa.Column("normalization_notes", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["raw_record_id"], ["raw_records.id"]),
        sa.ForeignKeyConstraint(["source_document_id"], ["source_documents.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "development_records",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("public_id", sa.String(length=255), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("development_type", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=100), nullable=False),
        sa.Column("source_status", sa.String(length=100), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("source_agency_id", sa.Integer(), nullable=True),
        sa.Column("date_discovered", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("date_last_checked", sa.DateTime(timezone=True), nullable=True),
        sa.Column("application_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approval_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("permit_issue_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_status", sa.String(length=50), nullable=False),
        sa.Column("confidence_level", sa.String(length=50), nullable=False),
        sa.Column("geometry_source", sa.String(length=255), nullable=True),
        sa.Column("geometry_confidence", sa.String(length=50), nullable=True),
        sa.Column(
            "canonical_geometry",
            geoalchemy2.types.Geometry(geometry_type="GEOMETRY", srid=4326),
            nullable=True,
        ),
        sa.Column(
            "centroid",
            geoalchemy2.types.Geometry(geometry_type="POINT", srid=4326),
            nullable=True,
        ),
        sa.Column("area_sq_m", sa.Float(), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("parcel_ids", sa.JSON(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["source_agency_id"], ["agencies.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id"),
    )
    op.create_table(
        "record_geometries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("development_record_id", sa.Integer(), nullable=False),
        sa.Column(
            "geometry",
            geoalchemy2.types.Geometry(geometry_type="GEOMETRY", srid=4326),
            nullable=False,
        ),
        sa.Column("geometry_role", sa.String(length=100), nullable=False),
        sa.Column("source_srid", sa.Integer(), nullable=True),
        sa.Column("source_description", sa.Text(), nullable=True),
        sa.Column("confidence_level", sa.String(length=50), nullable=True),
        sa.Column("created_by", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["development_record_id"], ["development_records.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "map_layers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("category", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("source_id", sa.Integer(), nullable=True),
        sa.Column("visibility_default", sa.Boolean(), nullable=False),
        sa.Column("min_zoom", sa.Float(), nullable=True),
        sa.Column("max_zoom", sa.Float(), nullable=True),
        sa.Column("tile_url", sa.Text(), nullable=True),
        sa.Column("attribution", sa.Text(), nullable=True),
        sa.Column("legend_json", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["source_id"], ["data_sources.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "environmental_layers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("category", sa.String(length=100), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=True),
        sa.Column("version", sa.String(length=100), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("loaded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("license_notes", sa.Text(), nullable=True),
        sa.Column("geom_type", sa.String(length=50), nullable=False),
        sa.ForeignKeyConstraint(["source_id"], ["data_sources.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "environmental_features",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("environmental_layer_id", sa.Integer(), nullable=False),
        sa.Column("source_feature_id", sa.String(length=255), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("attributes_json", sa.JSON(), nullable=True),
        sa.Column(
            "geometry",
            geoalchemy2.types.Geometry(geometry_type="GEOMETRY", srid=4326),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["environmental_layer_id"], ["environmental_layers.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "proximity_flags",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("development_record_id", sa.Integer(), nullable=False),
        sa.Column("environmental_layer_id", sa.Integer(), nullable=False),
        sa.Column("flag_type", sa.String(length=100), nullable=False),
        sa.Column("relationship", sa.String(length=100), nullable=False),
        sa.Column("distance_m", sa.Float(), nullable=True),
        sa.Column("threshold_m", sa.Float(), nullable=True),
        sa.Column("method", sa.String(length=255), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("layer_version", sa.String(length=100), nullable=True),
        sa.ForeignKeyConstraint(["development_record_id"], ["development_records.id"]),
        sa.ForeignKeyConstraint(["environmental_layer_id"], ["environmental_layers.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "review_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("record_id", sa.Integer(), nullable=True),
        sa.Column("staged_record_id", sa.Integer(), nullable=True),
        sa.Column("user_id", sa.String(length=255), nullable=True),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("from_status", sa.String(length=50), nullable=True),
        sa.Column("to_status", sa.String(length=50), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["record_id"], ["development_records.id"]),
        sa.ForeignKeyConstraint(["staged_record_id"], ["staged_development_records.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "record_versions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("development_record_id", sa.Integer(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("snapshot_json", sa.JSON(), nullable=False),
        sa.Column("changed_by", sa.String(length=255), nullable=True),
        sa.Column("changed_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["development_record_id"], ["development_records.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "user_submissions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("submitter_contact_hash", sa.String(length=255), nullable=True),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "geometry",
            geoalchemy2.types.Geometry(geometry_type="GEOMETRY", srid=4326),
            nullable=True,
        ),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "watch_areas",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.String(length=255), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column(
            "geometry",
            geoalchemy2.types.Geometry(geometry_type="GEOMETRY", srid=4326),
            nullable=False,
        ),
        sa.Column("filters_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "alerts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("watch_area_id", sa.Integer(), nullable=False),
        sa.Column("development_record_id", sa.Integer(), nullable=False),
        sa.Column("alert_type", sa.String(length=100), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.ForeignKeyConstraint(["development_record_id"], ["development_records.id"]),
        sa.ForeignKeyConstraint(["watch_area_id"], ["watch_areas.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_development_records_canonical_geometry",
        "development_records",
        ["canonical_geometry"],
        postgresql_using="gist",
    )
    op.create_index(
        "ix_development_records_centroid",
        "development_records",
        ["centroid"],
        postgresql_using="gist",
    )
    op.create_index(
        "ix_staged_development_records_geometry",
        "staged_development_records",
        ["geometry"],
        postgresql_using="gist",
    )
    op.create_index(
        "ix_record_geometries_geometry",
        "record_geometries",
        ["geometry"],
        postgresql_using="gist",
    )
    op.create_index(
        "ix_environmental_features_geometry",
        "environmental_features",
        ["geometry"],
        postgresql_using="gist",
    )
    op.create_index(
        "ix_user_submissions_geometry",
        "user_submissions",
        ["geometry"],
        postgresql_using="gist",
    )
    op.create_index(
        "ix_watch_areas_geometry",
        "watch_areas",
        ["geometry"],
        postgresql_using="gist",
    )


def downgrade() -> None:
    op.drop_index("ix_watch_areas_geometry", table_name="watch_areas")
    op.drop_index("ix_user_submissions_geometry", table_name="user_submissions")
    op.drop_index("ix_environmental_features_geometry", table_name="environmental_features")
    op.drop_index("ix_record_geometries_geometry", table_name="record_geometries")
    op.drop_index("ix_staged_development_records_geometry", table_name="staged_development_records")
    op.drop_index("ix_development_records_centroid", table_name="development_records")
    op.drop_index("ix_development_records_canonical_geometry", table_name="development_records")

    for table in [
        "alerts",
        "watch_areas",
        "user_submissions",
        "record_versions",
        "review_events",
        "proximity_flags",
        "environmental_features",
        "environmental_layers",
        "map_layers",
        "record_geometries",
        "development_records",
        "staged_development_records",
        "raw_records",
        "source_documents",
        "ingestion_runs",
        "data_sources",
        "agencies",
    ]:
        op.drop_table(table)
