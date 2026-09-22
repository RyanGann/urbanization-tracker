from typing import Any, Literal

from email_validator import EmailNotValidError, validate_email
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    SerializerFunctionWrapHandler,
    TypeAdapter,
    ValidationError,
    field_serializer,
    field_validator,
    model_serializer,
)

from app.data_availability import Availability, DataUnavailableError
from app.filters import SUPPORTED_DEVELOPMENT_TYPES, SUPPORTED_STATUSES
from app.public_fields import public_source_fields
from app.public_geometry import validate_geometry_structure

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

    @field_serializer("source_fields")
    def safe_source_fields(self, value: dict[str, Any]) -> dict[str, Any]:
        return public_source_fields(value)

    @field_serializer("geometry")
    def safe_geometry_members(self, value: GeoJSONGeometry) -> GeoJSONGeometry:
        return {"type": value.get("type"), "coordinates": value.get("coordinates")}


class DevelopmentRecordCollection(BaseModel):
    data_mode: Literal["live", "demo"]
    records: list[DevelopmentRecord]


class DatasetStatus(BaseModel):
    data_mode: Literal["live", "demo"]
    availability: Literal["ready", "uninitialized", "unavailable"]
    dataset_revision: str | None = None
    source_freshness: str | None = None
    declared_scope: str | None = None


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
    geometry: GeoJSONGeometry | None
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
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=3, max_length=200)
    source_url: str | None = Field(default=None, max_length=1000)
    notes: str = Field(min_length=5, max_length=2000)
    submitter_contact: str | None = Field(default=None, max_length=255)
    geometry: GeoJSONGeometry | None = None

    @field_validator("source_url")
    @classmethod
    def source_link_is_http(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = TypeAdapter(HttpUrl).validate_python(value)
        if parsed.username or parsed.password:
            raise ValueError("Source links cannot contain credentials.")
        return str(parsed)

    @field_validator("geometry")
    @classmethod
    def geometry_is_supported(cls, value: GeoJSONGeometry | None) -> GeoJSONGeometry | None:
        return None if value is None else validate_geometry_structure(value)

    @field_validator("submitter_contact")
    @classmethod
    def contact_is_email(cls, value: str | None) -> str | None:
        return None if value is None else normalized_email(value)


class UserSubmission(BaseModel):
    id: str
    title: str
    source_url: str | None = None
    notes: str
    submitter_contact_hash: str | None = None
    status: ReviewStatus
    created_at: str
    staged_record_id: str


class UserSubmissionReceipt(BaseModel):
    id: str
    title: str
    status: ReviewStatus
    created_at: str


class WatchAreaCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=3, max_length=120)
    email: str = Field(min_length=3, max_length=255)
    geometry: GeoJSONGeometry
    filters: dict[str, Any] = Field(default_factory=dict)

    @field_validator("email")
    @classmethod
    def email_must_be_deliverable_shape(cls, value: str) -> str:
        return normalized_email(value)

    @field_validator("geometry")
    @classmethod
    def geometry_is_supported(cls, value: GeoJSONGeometry) -> GeoJSONGeometry:
        return validate_geometry_structure(value, watch=True)

    @field_validator("filters")
    @classmethod
    def filters_are_supported(cls, value: dict[str, Any]) -> dict[str, Any]:
        options = {"statuses": SUPPORTED_STATUSES, "development_types": SUPPORTED_DEVELOPMENT_TYPES}
        if set(value) - set(options):
            raise ValueError("Unsupported watch filter.")
        for name, selected in value.items():
            if (
                not isinstance(selected, list)
                or len(selected) > len(options[name])
                or any(not isinstance(item, str) or item not in options[name] for item in selected)
            ):
                raise ValueError("Watch filters must be lists of supported values.")
        return value


def normalized_email(value: str) -> str:
    try:
        # Syntax only: no DNS/network. Reserved .test domains support isolated fixtures.
        return str(
            validate_email(
                value.strip(), check_deliverability=False, test_environment=True
            ).normalized
        )
    except EmailNotValidError as exc:
        raise ValueError("Enter a valid email address.") from exc


class WatchArea(BaseModel):
    id: str
    name: str
    email_hash: str
    email_hint: str
    geometry: GeoJSONGeometry
    filters: dict[str, Any] = Field(default_factory=dict)
    created_at: str
    alert_count: int = 0


class WatchAreaReceipt(BaseModel):
    id: str
    name: str
    email_hint: str
    created_at: str
    alert_count: int = 0


class UnsubscribeReceipt(BaseModel):
    id: str
    name: str
    email_hint: str
    unsubscribed_at: str


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


class AlertDeliveryResult(BaseModel):
    configured: bool
    attempted: int
    sent: int
    suppressed: int
    failed: int
    errors: list[str] = Field(default_factory=list)


class Phase3StoreCollectionStatus(BaseModel):
    name: str
    database_count: int
    artifact_count: int
    memory_count: int
    artifact_path: str
    artifact_error: str | None = None
    requires_migration: bool


class Phase3StoreStatus(BaseModel):
    backend: str
    database_first: bool
    database_error: str | None = None
    raw_artifact_root: str
    collections: list[Phase3StoreCollectionStatus]


class ProcessedStoreCollectionStatus(BaseModel):
    name: str
    database_count: int
    artifact_count: int
    requires_migration: bool


class RawArtifactStatus(BaseModel):
    name: str
    artifact_count: int


class ProcessedStoreStatus(BaseModel):
    backend: str
    database_first: bool
    database_error: str | None = None
    collections: list[ProcessedStoreCollectionStatus]
    raw_artifacts: list[RawArtifactStatus]


class RecordVersion(BaseModel):
    id: str
    public_id: str
    version_number: int
    changed_at: str
    changed_by: str
    change_type: str
    snapshot: dict[str, Any]

    @field_validator("snapshot")
    @classmethod
    def safe_public_snapshot(cls, value: dict[str, Any]) -> dict[str, Any]:
        # Public history uses the same schema as current detail, including nested allowlists.
        try:
            return DevelopmentRecord.model_validate(value).model_dump()
        except ValidationError:
            raise DataUnavailableError(
                collection="record_versions", availability=Availability.UNAVAILABLE
            ) from None


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


class MapLayerCoverage(BaseModel):
    status: str
    scope_id: str | None = None
    reported_count: int | None = Field(default=None, ge=0)
    fetched_count: int | None = Field(default=None, ge=0)


class MapLayer(BaseModel):
    id: str
    kind: Literal["vector"]
    title: str
    category: str
    data_version: str | None = None
    display_version: str | None = None
    delivery_status: Literal["unavailable", "processing", "ready", "failed", "withheld"]
    tile_url: str | None = None
    source_layer: str | None = None
    minzoom: int | None = Field(default=None, ge=0, le=24)
    maxzoom: int | None = Field(default=None, ge=0, le=24)
    bounds: tuple[float, float, float, float] | None = None
    coverage: MapLayerCoverage
    source_name: str
    source_url: str
    attribution: str
    caveat: str
    data_as_of: str | None = None
    fetched_at: str | None = None
    default_visible: bool = False


class LayerImportProgress(BaseModel):
    layer_id: str = Field(max_length=100)
    data_version: str = Field(min_length=64, max_length=64)
    status: Literal["loading", "validated", "failed"]
    expected: int | None = Field(default=None, ge=0)
    seen: int = Field(ge=0)
    accepted: int = Field(ge=0)
    rejected: int = Field(ge=0)
    checkpoint: int = Field(ge=0)


class MapLayerCatalog(BaseModel):
    data_mode: Literal["live", "demo"]
    catalog_revision: str
    layers: list[MapLayer] = Field(default_factory=list)
    imports: list[LayerImportProgress] = Field(default_factory=list, max_length=50)

    @field_validator("imports")
    @classmethod
    def unique_import_layers(cls, value: list[LayerImportProgress]) -> list[LayerImportProgress]:
        if len({item.layer_id for item in value}) != len(value):
            raise ValueError("Only one latest import per layer is allowed")
        return value

    @model_serializer(mode="wrap")
    def omit_absent_imports(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        result: dict[str, Any] = handler(self)
        if "imports" not in self.model_fields_set:
            result.pop("imports", None)
        return result

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
    data_mode: Literal["live", "demo"] | None = None
