from typing import Any, Literal

from pydantic import BaseModel, Field

GeoJSONGeometry = dict[str, Any]

DevelopmentStatus = Literal[
    "layout",
    "preliminary",
    "final",
    "issued_permit",
    "completed",
    "proposed",
]
ReviewStatus = Literal["pending", "needs_info", "rejected", "approved", "published"]
ConfidenceLevel = Literal["low", "medium", "high"]


class ProximityFlag(BaseModel):
    flag_type: str
    label: str
    relationship: str
    distance_m: float | None = None
    threshold_m: float | None = None
    source_name: str
    source_url: str
    caveat: str


class DevelopmentRecord(BaseModel):
    public_id: str
    title: str
    description: str
    development_type: str
    status: DevelopmentStatus
    source_status: str
    source_url: str
    source_agency: str
    date_discovered: str
    date_last_checked: str
    application_date: str | None = None
    approval_date: str | None = None
    permit_issue_date: str | None = None
    review_status: ReviewStatus
    confidence_level: ConfidenceLevel
    geometry_source: str
    geometry_confidence: ConfidenceLevel
    geometry: GeoJSONGeometry
    centroid: tuple[float, float]
    area_sq_m: float | None = None
    address: str | None = None
    parcel_ids: list[str] = Field(default_factory=list)
    source_fields: dict[str, Any] = Field(default_factory=dict)
    proximity_flags: list[ProximityFlag] = Field(default_factory=list)


class DevelopmentRecordCollection(BaseModel):
    records: list[DevelopmentRecord]


class StagedDevelopmentRecord(BaseModel):
    id: str
    title: str
    description: str
    development_type: str
    source_status: str
    normalized_status: DevelopmentStatus
    source_url: str
    source_agency: str
    date_discovered: str
    review_status: ReviewStatus
    record_confidence: ConfidenceLevel
    geometry_source: str
    geometry_confidence: ConfidenceLevel
    geometry: GeoJSONGeometry
    source_payload: dict[str, Any] = Field(default_factory=dict)
    normalization_notes: str


class ReviewDecision(BaseModel):
    notes: str | None = Field(default=None, max_length=1000)


class SourceDocument(BaseModel):
    id: str
    title: str
    url: str
    document_date: str | None = None
    fetched_at: str | None = None
    sha256: str | None = None
    content_type: str | None = None
    storage_uri: str | None = None
    extracted_text_uri: str | None = None
    extraction_status: str
    parsed_item_count: int = 0
    text_excerpt: str | None = None


class UserSubmissionCreate(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    source_url: str | None = Field(default=None, max_length=1000)
    notes: str = Field(min_length=5, max_length=2000)
    submitter_contact: str | None = Field(default=None, max_length=255)
    geometry: GeoJSONGeometry | None = None


class UserSubmission(BaseModel):
    id: str
    title: str
    source_url: str | None = None
    notes: str
    submitter_contact_hash: str | None = None
    status: ReviewStatus
    created_at: str
    staged_record_id: str


class WatchAreaCreate(BaseModel):
    name: str = Field(min_length=3, max_length=120)
    email: str = Field(min_length=3, max_length=255)
    geometry: GeoJSONGeometry
    filters: dict[str, Any] = Field(default_factory=dict)


class WatchArea(BaseModel):
    id: str
    name: str
    email_hash: str
    email_hint: str
    geometry: GeoJSONGeometry
    filters: dict[str, Any] = Field(default_factory=dict)
    created_at: str
    alert_count: int = 0


class Alert(BaseModel):
    id: str
    watch_area_id: str
    record_public_id: str
    record_title: str
    alert_type: str
    status: str
    delivery_channel: str
    created_at: str
    sent_at: str | None = None
    summary: str


class RecordVersion(BaseModel):
    id: str
    public_id: str
    version_number: int
    changed_at: str
    changed_by: str
    change_type: str
    snapshot: dict[str, Any]


class ChangeLogEntry(BaseModel):
    id: str
    public_id: str
    title: str
    changed_at: str
    change_type: str
    summary: str


class DuplicateCandidate(BaseModel):
    id: str
    staged_record_id: str
    staged_title: str
    candidate_public_id: str
    candidate_title: str
    score: float
    reasons: list[str] = Field(default_factory=list)


class JurisdictionSource(BaseModel):
    key: str
    name: str
    connector_type: str
    parser_key: str
    source_url: str
    active: bool
    privacy_review: str
    safety_review: str
    config: dict[str, Any] = Field(default_factory=dict)


class Jurisdiction(BaseModel):
    id: str
    name: str
    state: str
    country: str
    timezone: str
    default_center: tuple[float, float]
    sources: list[JurisdictionSource]


class ConnectorHealth(BaseModel):
    key: str
    name: str
    jurisdiction_id: str
    jurisdiction_name: str
    connector_type: str
    parser_key: str
    source_url: str
    active: bool
    status: str
    records_seen: int
    records_created: int
    error_count: int
    last_checked_at: str | None = None
    privacy_review: str
    safety_review: str


class ReviewerDecisionSnapshot(BaseModel):
    staged_id: str
    title: str
    source_url: str
    review_status: ReviewStatus
    review_notes: str | None = None
    exported_at: str


class ReviewerDecisionImportItem(BaseModel):
    staged_id: str
    review_status: ReviewStatus
    notes: str | None = Field(default=None, max_length=1000)


class ReviewerDecisionImport(BaseModel):
    decisions: list[ReviewerDecisionImportItem]


class ReviewerDecisionImportResult(BaseModel):
    applied: int
    missing: list[str] = Field(default_factory=list)


class EnvironmentalOverlay(BaseModel):
    id: str
    name: str
    category: str
    source_url: str
    attribution: str
    caveat: str
    geom_type: Literal["polygon", "line", "point"]
    features: dict[str, Any]


class FeatureCollection(BaseModel):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[dict[str, Any]]
