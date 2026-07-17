from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware

from app.alert_delivery import send_queued_email_alerts
from app.auth import require_reviewer_access
from app.config import get_settings
from app.jurisdictions import connector_health, list_jurisdictions
from app.phase3_store import (
    change_log_for,
    create_public_submission,
    create_watch_area,
    list_alerts,
    list_duplicate_candidates,
    list_public_submissions,
    list_source_documents,
    list_watch_areas,
    phase3_store_status,
    record_versions_for,
    set_public_submission_status,
)
from app.processed_store import processed_store_status
from app.schemas import (
    Alert,
    AlertDeliveryResult,
    ChangeLogEntry,
    ConnectorHealth,
    DevelopmentRecord,
    DevelopmentRecordCollection,
    DuplicateCandidate,
    EnvironmentalOverlay,
    FeatureCollection,
    Jurisdiction,
    Phase3StoreStatus,
    ProcessedStoreStatus,
    RecordVersion,
    ReviewDecision,
    ReviewerDecisionImport,
    ReviewerDecisionImportResult,
    ReviewerDecisionSnapshot,
    SourceDocument,
    StagedDevelopmentRecord,
    UnsubscribeReceipt,
    UserSubmission,
    UserSubmissionCreate,
    UserSubmissionReceipt,
    WatchArea,
    WatchAreaCreate,
    WatchAreaReceipt,
)
from app.seed_store import (
    approve_staged_record,
    development_records_geojson,
    export_reviewer_decisions,
    get_development_record,
    import_reviewer_decisions,
    list_development_records,
    list_environmental_overlays,
    list_staged_records,
    load_source_health,
    set_staged_review_status,
)
from app.source_monitoring import build_source_health_monitor

settings = get_settings()
reviewer_router = APIRouter(
    prefix="/api/reviewer",
    dependencies=[Depends(require_reviewer_access)],
)

app = FastAPI(title=settings.app_name, version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "urbanization-tracker-api"}


@app.get("/health/source-health")
def source_health_monitor(
    response: Response,
    max_age_hours: Annotated[int | None, Query(ge=1, le=720)] = None,
) -> dict[str, object]:
    payload = build_source_health_monitor(max_age_hours=max_age_hours)
    if payload["status"] != "healthy":
        response.status_code = 503
    return payload


@app.get("/api/development-records", response_model=DevelopmentRecordCollection)
def get_development_records(
    status: Annotated[list[str] | None, Query()] = None,
    development_type: Annotated[list[str] | None, Query()] = None,
    confidence: Annotated[list[str] | None, Query()] = None,
    flag: Annotated[list[str] | None, Query()] = None,
) -> DevelopmentRecordCollection:
    records = list_development_records(
        statuses=status,
        development_types=development_type,
        confidence_levels=confidence,
        flag_types=flag,
    )
    return DevelopmentRecordCollection(records=records)


@app.get("/api/development-records/{public_id}", response_model=DevelopmentRecord)
def get_development_record_detail(public_id: str) -> DevelopmentRecord:
    record = get_development_record(public_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Development record not found")
    return record


@app.get(
    "/api/development-records/{public_id}/versions",
    response_model=list[RecordVersion],
)
def get_development_record_versions(public_id: str) -> list[RecordVersion]:
    record = get_development_record(public_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Development record not found")
    return [
        RecordVersion.model_validate(version)
        for version in record_versions_for(public_id, record)
    ]


@app.get("/api/map/development-records.geojson", response_model=FeatureCollection)
def get_development_records_geojson(
    status: Annotated[list[str] | None, Query()] = None,
    development_type: Annotated[list[str] | None, Query()] = None,
    confidence: Annotated[list[str] | None, Query()] = None,
    flag: Annotated[list[str] | None, Query()] = None,
) -> dict[str, object]:
    records = list_development_records(
        statuses=status,
        development_types=development_type,
        confidence_levels=confidence,
        flag_types=flag,
    )
    return development_records_geojson(records)


@app.get("/api/environmental-overlays", response_model=list[EnvironmentalOverlay])
def get_environmental_overlays() -> list[EnvironmentalOverlay]:
    return list_environmental_overlays()


@app.get("/api/source-health")
def get_source_health() -> dict[str, object]:
    return load_source_health()


@app.get("/api/jurisdictions", response_model=list[Jurisdiction])
def get_jurisdictions() -> list[Jurisdiction]:
    return [
        Jurisdiction.model_validate(jurisdiction.model_dump())
        for jurisdiction in list_jurisdictions()
    ]


@app.get("/api/connector-health", response_model=list[ConnectorHealth])
def get_connector_health() -> list[ConnectorHealth]:
    return [
        ConnectorHealth.model_validate(row.model_dump())
        for row in connector_health(load_source_health())
    ]


@app.get("/api/source-documents", response_model=list[SourceDocument])
def get_source_documents() -> list[SourceDocument]:
    return [SourceDocument.model_validate(document) for document in list_source_documents()]


@app.get("/api/change-log", response_model=list[ChangeLogEntry])
def get_change_log(limit: int = 50) -> list[ChangeLogEntry]:
    records = list_development_records()
    return [ChangeLogEntry.model_validate(entry) for entry in change_log_for(records, limit=limit)]


@reviewer_router.get("/duplicate-candidates", response_model=list[DuplicateCandidate])
def get_duplicate_candidates() -> list[DuplicateCandidate]:
    return [
        DuplicateCandidate.model_validate(candidate)
        for candidate in list_duplicate_candidates()
    ]


@reviewer_router.get("/public-submissions", response_model=list[UserSubmission])
def get_reviewer_public_submissions() -> list[UserSubmission]:
    return [
        UserSubmission.model_validate(submission)
        for submission in list_public_submissions()
    ]


@app.post("/api/public-submissions", response_model=UserSubmissionReceipt)
def post_public_submission(submission: UserSubmissionCreate) -> UserSubmissionReceipt:
    created = create_public_submission(
        submission.model_dump(),
        published_records=list_development_records(),
    )
    return UserSubmissionReceipt.model_validate(created)


@reviewer_router.get("/watch-areas", response_model=list[WatchArea])
def get_reviewer_watch_areas() -> list[WatchArea]:
    return [WatchArea.model_validate(watch_area) for watch_area in list_watch_areas()]


@app.post("/api/watch-areas", response_model=WatchAreaReceipt)
def post_watch_area(watch_area: WatchAreaCreate) -> WatchAreaReceipt:
    created = create_watch_area(watch_area.model_dump(), list_development_records())
    return WatchAreaReceipt.model_validate(created)


@app.get("/api/watch-areas/unsubscribe/{token}", response_model=UnsubscribeReceipt)
def get_unsubscribe_watch_area(token: str) -> UnsubscribeReceipt:
    from app.phase3_store import unsubscribe_watch_area

    watch_area = unsubscribe_watch_area(token)
    if watch_area is None:
        raise HTTPException(status_code=404, detail="Watch area subscription not found")
    return UnsubscribeReceipt.model_validate(watch_area)


@reviewer_router.get("/alerts", response_model=list[Alert])
def get_reviewer_alerts() -> list[Alert]:
    return [Alert.model_validate(alert) for alert in list_alerts()]


@reviewer_router.get("/phase3-store", response_model=Phase3StoreStatus)
def get_reviewer_phase3_store_status() -> Phase3StoreStatus:
    return Phase3StoreStatus.model_validate(phase3_store_status())


@reviewer_router.get("/processed-store", response_model=ProcessedStoreStatus)
def get_reviewer_processed_store_status() -> ProcessedStoreStatus:
    payload = processed_store_status()
    if payload.get("database_error"):
        payload["database_error"] = "Database status check failed."
    return ProcessedStoreStatus.model_validate(payload)


@reviewer_router.post("/alerts/send", response_model=AlertDeliveryResult)
def post_reviewer_send_alerts(limit: int | None = None) -> AlertDeliveryResult:
    return AlertDeliveryResult.model_validate(send_queued_email_alerts(limit=limit))


@reviewer_router.get("/staged-records", response_model=list[StagedDevelopmentRecord])
def get_reviewer_queue() -> list[StagedDevelopmentRecord]:
    return list_staged_records()


@reviewer_router.get(
    "/decisions/export",
    response_model=list[ReviewerDecisionSnapshot],
)
def export_reviewer_decision_snapshot() -> list[ReviewerDecisionSnapshot]:
    return [
        ReviewerDecisionSnapshot.model_validate(decision)
        for decision in export_reviewer_decisions()
    ]


@reviewer_router.post(
    "/decisions/import",
    response_model=ReviewerDecisionImportResult,
)
def import_reviewer_decision_snapshot(
    payload: ReviewerDecisionImport,
) -> ReviewerDecisionImportResult:
    result = import_reviewer_decisions(
        [decision.model_dump() for decision in payload.decisions]
    )
    return ReviewerDecisionImportResult.model_validate(result)


@reviewer_router.post("/staged-records/{staged_id}/approve", response_model=DevelopmentRecord)
def approve_reviewer_record(staged_id: str, decision: ReviewDecision) -> DevelopmentRecord:
    record = approve_staged_record(staged_id, notes=decision.notes)
    if record is None:
        raise HTTPException(status_code=404, detail="Staged record not found")
    return record


@reviewer_router.post("/staged-records/{staged_id}/reject", response_model=StagedDevelopmentRecord)
def reject_reviewer_record(staged_id: str, decision: ReviewDecision) -> StagedDevelopmentRecord:
    staged = set_staged_review_status(staged_id, "rejected", notes=decision.notes)
    if staged is None:
        raise HTTPException(status_code=404, detail="Staged record not found")
    return staged


@reviewer_router.post(
    "/staged-records/{staged_id}/needs-info",
    response_model=StagedDevelopmentRecord,
)
def mark_reviewer_record_needs_info(
    staged_id: str, decision: ReviewDecision
) -> StagedDevelopmentRecord:
    staged = set_staged_review_status(staged_id, "needs_info", notes=decision.notes)
    if staged is None:
        raise HTTPException(status_code=404, detail="Staged record not found")
    return staged


@reviewer_router.get("/submissions", response_model=list[UserSubmission])
def get_reviewer_submissions() -> list[UserSubmission]:
    return [
        UserSubmission.model_validate(submission)
        for submission in list_public_submissions()
    ]


@reviewer_router.post("/submissions/{submission_id}/approve", response_model=UserSubmission)
def approve_public_submission(
    submission_id: str, decision: ReviewDecision
) -> UserSubmission:
    submission = set_public_submission_status(submission_id, "approved", notes=decision.notes)
    if submission is None:
        raise HTTPException(status_code=404, detail="Submission not found")
    return UserSubmission.model_validate(submission)


@reviewer_router.post("/submissions/{submission_id}/reject", response_model=UserSubmission)
def reject_public_submission(
    submission_id: str, decision: ReviewDecision
) -> UserSubmission:
    submission = set_public_submission_status(submission_id, "rejected", notes=decision.notes)
    if submission is None:
        raise HTTPException(status_code=404, detail="Submission not found")
    return UserSubmission.model_validate(submission)


@reviewer_router.post("/submissions/{submission_id}/needs-info", response_model=UserSubmission)
def mark_public_submission_needs_info(
    submission_id: str, decision: ReviewDecision
) -> UserSubmission:
    submission = set_public_submission_status(submission_id, "needs_info", notes=decision.notes)
    if submission is None:
        raise HTTPException(status_code=404, detail="Submission not found")
    return UserSubmission.model_validate(submission)


app.include_router(reviewer_router)
