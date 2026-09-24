from datetime import datetime
from typing import Any

from geoalchemy2 import Geometry
from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Agency(Base):
    __tablename__ = "agencies"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    jurisdiction_name: Mapped[str | None] = mapped_column(String(255))
    jurisdiction_type: Mapped[str | None] = mapped_column(String(100))
    website_url: Mapped[str | None] = mapped_column(Text)
    contact_url: Mapped[str | None] = mapped_column(Text)

    data_sources: Mapped[list["DataSource"]] = relationship(back_populates="agency")


class DataSource(Base):
    __tablename__ = "data_sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    agency_id: Mapped[int] = mapped_column(ForeignKey("agencies.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_type: Mapped[str] = mapped_column(String(100), nullable=False)
    base_url: Mapped[str] = mapped_column(Text, nullable=False)
    license_notes: Mapped[str | None] = mapped_column(Text)
    attribution: Mapped[str | None] = mapped_column(Text)
    update_cadence: Mapped[str | None] = mapped_column(String(100))
    connector_key: Mapped[str | None] = mapped_column(String(255))
    connector_config_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    health_status: Mapped[str] = mapped_column(String(50), default="unknown", nullable=False)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    agency: Mapped[Agency] = relationship(back_populates="data_sources")


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    data_source_id: Mapped[int] = mapped_column(ForeignKey("data_sources.id"), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    records_seen: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    records_created: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    records_updated: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    records_skipped: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    log_uri: Mapped[str | None] = mapped_column(Text)
    source_window_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_window_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SourceDocument(Base):
    __tablename__ = "source_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    data_source_id: Mapped[int] = mapped_column(ForeignKey("data_sources.id"), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    document_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sha256: Mapped[str | None] = mapped_column(String(64))
    content_type: Mapped[str | None] = mapped_column(String(255))
    storage_uri: Mapped[str | None] = mapped_column(Text)
    extracted_text: Mapped[str | None] = mapped_column(Text)
    extraction_status: Mapped[str | None] = mapped_column(String(50))


class RawRecord(Base):
    __tablename__ = "raw_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    data_source_id: Mapped[int] = mapped_column(ForeignKey("data_sources.id"), nullable=False)
    ingestion_run_id: Mapped[int | None] = mapped_column(ForeignKey("ingestion_runs.id"))
    source_record_id: Mapped[str] = mapped_column(String(255), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    payload_sha256: Mapped[str | None] = mapped_column(String(64))


class StagedDevelopmentRecord(Base):
    __tablename__ = "staged_development_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    raw_record_id: Mapped[int | None] = mapped_column(ForeignKey("raw_records.id"))
    source_document_id: Mapped[int | None] = mapped_column(ForeignKey("source_documents.id"))
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    development_type: Mapped[str | None] = mapped_column(String(100))
    source_status: Mapped[str | None] = mapped_column(String(100))
    normalized_status: Mapped[str | None] = mapped_column(String(100))
    application_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approval_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    permit_issue_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    date_discovered: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    date_last_checked: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_agency: Mapped[str | None] = mapped_column(String(255))
    address: Mapped[str | None] = mapped_column(Text)
    parcel_ids: Mapped[list[str] | None] = mapped_column(JSON)
    geometry: Mapped[Any | None] = mapped_column(Geometry("GEOMETRY", srid=4326))
    geometry_source: Mapped[str | None] = mapped_column(String(255))
    geometry_confidence: Mapped[str | None] = mapped_column(String(50))
    record_confidence: Mapped[str | None] = mapped_column(String(50))
    review_status: Mapped[str] = mapped_column(String(50), default="pending", nullable=False)
    normalization_notes: Mapped[str | None] = mapped_column(Text)


class DevelopmentRecord(Base):
    __tablename__ = "development_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    public_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    development_type: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(100), nullable=False)
    source_status: Mapped[str | None] = mapped_column(String(100))
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_agency_id: Mapped[int | None] = mapped_column(ForeignKey("agencies.id"))
    date_discovered: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    date_last_checked: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    application_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approval_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    permit_issue_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_status: Mapped[str] = mapped_column(String(50), default="published", nullable=False)
    confidence_level: Mapped[str] = mapped_column(String(50), nullable=False)
    geometry_source: Mapped[str | None] = mapped_column(String(255))
    geometry_confidence: Mapped[str | None] = mapped_column(String(50))
    canonical_geometry: Mapped[Any | None] = mapped_column(Geometry("GEOMETRY", srid=4326))
    centroid: Mapped[Any | None] = mapped_column(Geometry("POINT", srid=4326))
    area_sq_m: Mapped[float | None] = mapped_column(Float)
    address: Mapped[str | None] = mapped_column(Text)
    parcel_ids: Mapped[list[str] | None] = mapped_column(JSON)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class RecordGeometry(Base):
    __tablename__ = "record_geometries"

    id: Mapped[int] = mapped_column(primary_key=True)
    development_record_id: Mapped[int] = mapped_column(
        ForeignKey("development_records.id"), nullable=False
    )
    geometry: Mapped[Any] = mapped_column(Geometry("GEOMETRY", srid=4326), nullable=False)
    geometry_role: Mapped[str] = mapped_column(String(100), nullable=False)
    source_srid: Mapped[int | None] = mapped_column(Integer)
    source_description: Mapped[str | None] = mapped_column(Text)
    confidence_level: Mapped[str | None] = mapped_column(String(50))
    created_by: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MapLayer(Base):
    __tablename__ = "map_layers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("data_sources.id"))
    visibility_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    min_zoom: Mapped[float | None] = mapped_column(Float)
    max_zoom: Mapped[float | None] = mapped_column(Float)
    tile_url: Mapped[str | None] = mapped_column(Text)
    attribution: Mapped[str | None] = mapped_column(Text)
    legend_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)


class EnvironmentalLayer(Base):
    __tablename__ = "environmental_layers"
    __table_args__ = (
        UniqueConstraint("layer_key", "data_version", name="uq_environmental_layer_version"),
        CheckConstraint(
            "(layer_key IS NULL) = (data_version IS NULL)",
            name="ck_environmental_layer_version_pair",
        ),
        CheckConstraint(
            "import_status IS NULL OR import_status IN ('loading', 'validated', 'failed')",
            name="ck_environmental_import_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("data_sources.id"))
    version: Mapped[str | None] = mapped_column(String(100))
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    loaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    license_notes: Mapped[str | None] = mapped_column(Text)
    geom_type: Mapped[str] = mapped_column(String(50), nullable=False)
    # Legacy scaffold rows deliberately keep version/provenance columns null.
    layer_key: Mapped[str | None] = mapped_column(String(100))
    data_version: Mapped[str | None] = mapped_column(String(64))
    source_checksum: Mapped[str | None] = mapped_column(String(64))
    importer_format: Mapped[str | None] = mapped_column(String(32))
    scope_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    import_status: Mapped[str | None] = mapped_column(String(16))
    coverage_status: Mapped[str | None] = mapped_column(String(16))
    expected_count: Mapped[int | None] = mapped_column(Integer)
    seen_count: Mapped[int | None] = mapped_column(Integer)
    accepted_count: Mapped[int | None] = mapped_column(Integer)
    rejected_count: Mapped[int | None] = mapped_column(Integer)
    duplicate_count: Mapped[int | None] = mapped_column(Integer)
    import_checkpoint: Mapped[int | None] = mapped_column(Integer)
    bounds_json: Mapped[list[float] | None] = mapped_column(JSON)
    diagnostics_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    import_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    import_finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EnvironmentalFeature(Base):
    __tablename__ = "environmental_features"
    __table_args__ = (
        Index(
            "uq_environmental_managed_feature", "environmental_layer_id", "source_feature_id",
            unique=True, postgresql_where=text("import_managed IS TRUE"),
        ),
        CheckConstraint(
            "NOT import_managed OR (source_feature_id IS NOT NULL "
            "AND btrim(source_feature_id) <> '')",
            name="ck_environmental_managed_feature_identity",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    environmental_layer_id: Mapped[int] = mapped_column(
        ForeignKey("environmental_layers.id"), nullable=False
    )
    source_feature_id: Mapped[str | None] = mapped_column(String(255))
    name: Mapped[str | None] = mapped_column(String(255))
    attributes_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    geometry: Mapped[Any] = mapped_column(Geometry("GEOMETRY", srid=4326), nullable=False)
    import_managed: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
    import_fingerprint: Mapped[str | None] = mapped_column(String(64))


class ProximityFlag(Base):
    __tablename__ = "proximity_flags"

    id: Mapped[int] = mapped_column(primary_key=True)
    development_record_id: Mapped[int] = mapped_column(
        ForeignKey("development_records.id"), nullable=False
    )
    environmental_layer_id: Mapped[int] = mapped_column(
        ForeignKey("environmental_layers.id"), nullable=False
    )
    flag_type: Mapped[str] = mapped_column(String(100), nullable=False)
    relationship: Mapped[str] = mapped_column(String(100), nullable=False)
    distance_m: Mapped[float | None] = mapped_column(Float)
    threshold_m: Mapped[float | None] = mapped_column(Float)
    method: Mapped[str] = mapped_column(String(255), nullable=False)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    layer_version: Mapped[str | None] = mapped_column(String(100))


class ReviewEvent(Base):
    __tablename__ = "review_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    record_id: Mapped[int | None] = mapped_column(ForeignKey("development_records.id"))
    staged_record_id: Mapped[int | None] = mapped_column(
        ForeignKey("staged_development_records.id")
    )
    user_id: Mapped[str | None] = mapped_column(String(255))
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(50))
    to_status: Mapped[str | None] = mapped_column(String(50))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RecordVersion(Base):
    __tablename__ = "record_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    development_record_id: Mapped[int] = mapped_column(
        ForeignKey("development_records.id"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    changed_by: Mapped[str | None] = mapped_column(String(255))
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserSubmission(Base):
    __tablename__ = "user_submissions"

    id: Mapped[int] = mapped_column(primary_key=True)
    submitter_contact_hash: Mapped[str | None] = mapped_column(String(255))
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    geometry: Mapped[Any | None] = mapped_column(Geometry("GEOMETRY", srid=4326))
    status: Mapped[str] = mapped_column(String(50), default="pending", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WatchArea(Base):
    __tablename__ = "watch_areas"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[str | None] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    geometry: Mapped[Any] = mapped_column(Geometry("GEOMETRY", srid=4326), nullable=False)
    filters_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    watch_area_id: Mapped[int] = mapped_column(ForeignKey("watch_areas.id"), nullable=False)
    development_record_id: Mapped[int] = mapped_column(
        ForeignKey("development_records.id"), nullable=False
    )
    alert_type: Mapped[str] = mapped_column(String(100), nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(50), default="pending", nullable=False)


class Phase3CollectionItem(Base):
    __tablename__ = "phase3_collection_items"
    __table_args__ = (
        UniqueConstraint("collection_name", "item_id", name="uq_phase3_collection_item"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    collection_name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    item_id: Mapped[str] = mapped_column(String(255), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ProcessedCollectionItem(Base):
    __tablename__ = "processed_collection_items"
    __table_args__ = (
        UniqueConstraint("collection_name", "item_id", name="uq_processed_collection_item"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    collection_name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    item_id: Mapped[str] = mapped_column(String(255), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class SourceIdentityRegistry(Base):
    """Stable source anchors retained independently from mutable public content."""

    __tablename__ = "source_identity_registry"
    __table_args__ = (
        UniqueConstraint("source_key", "source_record_id", name="uq_source_identity_anchor"),
        UniqueConstraint("public_id", name="uq_source_identity_public_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source_key: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    source_record_id: Mapped[str] = mapped_column(String(255), nullable=False)
    public_id: Mapped[str] = mapped_column(String(255), nullable=False)
    first_discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class SourceIngestionBatch(Base):
    """One source observation with explicit scope and coverage semantics."""

    __tablename__ = "source_ingestion_batches"
    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "source_key",
            "scope_id",
            "scope_version",
            name="uq_source_ingestion_batch_replay",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[str] = mapped_column(String(255), nullable=False)
    source_key: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    scope_id: Mapped[str] = mapped_column(String(255), nullable=False)
    scope_version: Mapped[str] = mapped_column(String(255), nullable=False)
    coverage: Mapped[str] = mapped_column(String(20), nullable=False)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)
    counts_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SourceObservation(Base):
    """Scope-specific observed/missing provenance; it never deletes canonical rows."""

    __tablename__ = "source_observations"
    __table_args__ = (
        UniqueConstraint("batch_id", "registry_id", name="uq_source_observation_batch_registry"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(
        ForeignKey("source_ingestion_batches.id"), nullable=False, index=True
    )
    registry_id: Mapped[int] = mapped_column(
        ForeignKey("source_identity_registry.id"), nullable=False, index=True
    )
    state: Mapped[str] = mapped_column(String(20), nullable=False)
    content_fingerprint: Mapped[str | None] = mapped_column(String(128))
    fingerprint_version: Mapped[str | None] = mapped_column(String(40))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PublicWriteQuota(Base):
    __tablename__ = "public_write_quotas"
    __table_args__ = (
        CheckConstraint("attempts BETWEEN 1 AND 1000", name="ck_public_quota_attempts"),
    )

    client_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    route: Mapped[str] = mapped_column(String(32), primary_key=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
