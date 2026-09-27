"""C04 real PostGIS/API checks with synthetic PDF/text bytes and O01 local manifest."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import tempfile
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import httpx
from sqlalchemy import func, select

from app.config import get_settings
from app.db import SessionLocal
from app.ingestion.agenda import parse_agenda_items
from app.ingestion.agenda_pipeline import ingest_huntsville_agendas
from app.ingestion.agenda_store import merge_agenda_artifacts
from app.ingestion.artifact_service import ArtifactService
from app.ingestion.artifact_sink import ArtifactError, BlobIdentity
from app.ingestion.connectors.agenda import AgendaLink
from app.models import Phase3CollectionItem
from app.phase3_store import _stable_id
from app.transactional_store import CollectionUnitOfWork

SOURCE = "huntsville_planning_agendas"
URL = "https://example.test/c04/agenda.pdf"


def count(collection: str) -> int:
    with SessionLocal() as session:
        return int(
            session.scalar(
                select(func.count())
                .select_from(Phase3CollectionItem)
                .where(Phase3CollectionItem.collection_name == collection)
            )
            or 0
        )


def setup_document(
    service: ArtifactService,
    root: Path,
    *,
    run_id: str,
    pdf: bytes,
    text: str,
    pending_text: bool = False,
    url: str = URL,
    date: str | None = "2026-04-28",
) -> tuple[dict, list[dict], tuple]:
    digest = hashlib.sha256(pdf).hexdigest()
    text_bytes = text.encode()
    text_digest = hashlib.sha256(text_bytes).hexdigest()
    pdf_path = root / f"{run_id}.pdf"
    pdf_path.write_bytes(pdf)
    pdf_ref = service.upload_file(
        path=pdf_path,
        source_key=SOURCE,
        run_id=run_id,
        artifact_type="source_pdf",
        logical_key="agenda-pdf",
        required=True,
        content_type="application/pdf",
        source_url=url,
    )
    text_path = root / f"{run_id}.txt"
    text_path.write_bytes(text_bytes)
    if pending_text:
        text_ref = service.manifest.reserve(
            blob=BlobIdentity(text_digest, len(text_bytes)),
            sink_id=service.sink_id,
            source_key=SOURCE,
            run_id=run_id,
            artifact_type="extracted_text",
            logical_key="agenda-text",
            required=True,
            parent_reference_id=pdf_ref,
            content_type="text/plain; charset=utf-8",
            source_url=url,
        )
    else:
        text_ref = service.upload_file(
            path=text_path,
            source_key=SOURCE,
            run_id=run_id,
            artifact_type="extracted_text",
            logical_key="agenda-text",
            required=True,
            content_type="text/plain; charset=utf-8",
            source_url=url,
            parent_reference_id=pdf_ref,
        )
    document = {
        "id": f"agenda-{digest[:12]}",
        "title": "Planning Commission Agenda - April 28, 2026",
        "url": url,
        "document_date": date,
        "fetched_at": "2026-09-24T12:00:00Z",
        "sha256": digest,
        "text_sha256": text_digest,
        "content_type": "application/pdf",
        "storage_uri": None,
        "extracted_text_uri": None,
        "extraction_status": "extracted",
        "pdf_reference_id": str(pdf_ref),
        "text_reference_id": str(text_ref),
        "parsed_item_count": 0,
        "text_excerpt": text[:100],
    }
    records = parse_agenda_items(text, source_document=document, checked_at="2026-09-24T12:00:00Z")
    document["parsed_item_count"] = len(records)
    return document, records, (pdf_ref, text_ref)


def merge(document: dict, records: list[dict], refs: tuple, run_id: str, sink_id: str) -> None:
    merge_agenda_artifacts(
        source_documents=[document],
        staged_records=records,
        health={"key": SOURCE, "status": "healthy", "checked_at": "2026-09-24T12:00:00Z"},
        run_id=run_id,
        artifact_sink_id=sink_id,
        required_reference_ids=refs,
    )


def run(api_url: str, reviewer_token: str, result: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="c04-integration-") as directory:
        root = Path(directory)
        settings = get_settings().model_copy(
            update={
                "data_mode": "live",
                "phase3_store_backend": "postgres",
                "processed_store_backend": "postgres",
                "ingestion_data_dir": root,
                "artifact_sink": "local",
                "artifact_local_root": root / "objects",
                "artifact_durability_required": True,
            }
        )
        service = ArtifactService(settings, SessionLocal)
        headers = {"Authorization": f"Bearer {reviewer_token}"}
        with patch("app.ingestion.agenda_store.get_settings", return_value=settings):
            with httpx.Client(base_url=api_url, headers=headers, timeout=15) as api:
                processed_public = api.get("/api/development-records").json()["records"][0]
                processed_public.update(public_id="c04-processed-duplicate", title="Sample Ridge")
                with SessionLocal.begin() as session:
                    with CollectionUnitOfWork(session).canonical_mutation() as uow:
                        uow.upsert_processed(
                            "development_records", processed_public["public_id"], processed_public
                        )
                first_run = "c04-first-" + uuid4().hex
                first_text = (
                    "1. SAMPLE RIDGE\nLayout (24 lots) Developer: Builder\nLocated: West of Road"
                )
                first, first_records, first_refs = setup_document(
                    service,
                    root,
                    run_id=first_run,
                    pdf=b"synthetic PDF revision one",
                    text=first_text,
                    pending_text=True,
                )
                before = count("source_documents")
                try:
                    merge(first, first_records, first_refs, first_run, service.sink_id)
                except ArtifactError as exc:
                    assert exc.code == "artifact_unavailable"
                else:
                    raise AssertionError("pending text activated an agenda")
                assert count("source_documents") == before
                service.resume(first_refs[1], root / f"{first_run}.txt")
                merge(first, first_records, first_refs, first_run, service.sink_id)
                queue = api.get("/api/reviewer/staged-records")
                assert queue.status_code == 200, queue.text
                candidate = next(row for row in queue.json() if row["source_url"] == URL)
                candidate_id = candidate["id"]
                processed_duplicate_id = _stable_id(
                    "duplicate", candidate_id, "c04-processed-duplicate"
                )
                assert any(
                    row["id"] == processed_duplicate_id
                    for row in api.get("/api/reviewer/duplicate-candidates").json()
                )
                assert candidate["geometry"] is None and candidate["state_revision"] == 1
                reject = api.post(
                    f"/api/reviewer/staged-records/{candidate_id}/reject",
                    json={"notes": "Source location unverified", "expected_revision": 1},
                )
                assert reject.status_code == 200, reject.text
                stale = api.post(
                    f"/api/reviewer/staged-records/{candidate_id}/needs-info",
                    json={"notes": "stale", "expected_revision": 1},
                )
                assert stale.status_code == 409
                assert stale.json()["detail"]["code"] == "review_revision_conflict"
                merge(first, first_records, first_refs, first_run, service.sink_id)
                queue = api.get("/api/reviewer/staged-records").json()
                replay = next(row for row in queue if row["id"] == candidate_id)
                assert replay["review_status"] == "rejected"
                assert replay["review_notes"] == "Source location unverified"
                assert replay["state_revision"] == 2

                next_run = "c04-next-" + uuid4().hex
                changed_text = (
                    "1. SAMPLE RIDGE\nFinal (24 lots) Developer: Builder\nLocated: West of Road"
                )
                changed, changed_records, changed_refs = setup_document(
                    service,
                    root,
                    run_id=next_run,
                    pdf=b"synthetic PDF revision two",
                    text=changed_text,
                    pending_text=True,
                )
                try:
                    merge(changed, changed_records, changed_refs, next_run, service.sink_id)
                except ArtifactError as exc:
                    assert exc.code == "artifact_unavailable"
                else:
                    raise AssertionError("pending changed PDF text activated")
                assert count("agenda_document_revisions") == 1
                service.resume(changed_refs[1], root / f"{next_run}.txt")
                merge(changed, changed_records, changed_refs, next_run, service.sink_id)
                unresolved = api.get("/api/reviewer/agenda-observations/unresolved")
                assert unresolved.status_code == 200, unresolved.text
                observation = next(
                    row for row in unresolved.json() if row["source_excerpt"] == "Sample Ridge"
                )
                old_candidate = next(
                    row
                    for row in api.get("/api/reviewer/staged-records").json()
                    if row["id"] == candidate_id
                )
                assert old_candidate["review_status"] == "rejected"
                stale_link = api.post(
                    f"/api/reviewer/agenda-observations/{observation['id']}/resolve",
                    json={
                        "candidate_id": candidate_id,
                        "expected_observation_revision": 1,
                        "expected_candidate_revision": 1,
                        "reason": "Reviewed source case continuity",
                    },
                )
                assert stale_link.status_code == 409
                linked = api.post(
                    f"/api/reviewer/agenda-observations/{observation['id']}/resolve",
                    json={
                        "candidate_id": candidate_id,
                        "expected_observation_revision": 1,
                        "expected_candidate_revision": 2,
                        "reason": "Reviewed source case continuity",
                    },
                )
                assert linked.status_code == 200, linked.text
                assert linked.json()["review_status"] == "pending"
                assert linked.json()["content_revision"] == 2
                assert count("agenda_decision_events") == 1
                with SessionLocal.begin() as session:
                    with CollectionUnitOfWork(session).canonical_mutation() as uow:
                        current = uow.get_phase3("agenda_staged_records", candidate_id)
                        assert current
                        current["geometry"] = {"type": "Point", "coordinates": [-86.58, 34.73]}
                        current["geometry_source"] = "reviewer-verified synthetic fixture"
                        current["geometry_confidence"] = "high"
                        current["location_required"] = False
                        current["state_revision"] += 1
                        uow.upsert_phase3("agenda_staged_records", candidate_id, current)
                approved_revision = linked.json()["state_revision"] + 1
                approved = api.post(
                    f"/api/reviewer/staged-records/{candidate_id}/approve",
                    json={
                        "notes": "Fixture location verified",
                        "expected_revision": approved_revision,
                    },
                )
                assert approved.status_code == 200, approved.text
                public_id = approved.json()["public_id"]
                merge(changed, changed_records, changed_refs, next_run, service.sink_id)
                assert count("agenda_candidate_revisions") == 2
                with SessionLocal() as session:
                    public_rows = session.scalars(
                        select(Phase3CollectionItem).where(
                            Phase3CollectionItem.collection_name == "development_records",
                            Phase3CollectionItem.item_id == public_id,
                        )
                    ).all()
                    assert len(public_rows) == 1
                    persisted_public = public_rows[0].payload_json
                current = next(
                    row
                    for row in api.get("/api/reviewer/staged-records").json()
                    if row["id"] == candidate_id
                )
                latest_document = api.get("/api/source-documents").json()
                historical_run = "c04-historical-" + uuid4().hex
                historical, historical_records, historical_refs = setup_document(
                    service,
                    root,
                    run_id=historical_run,
                    pdf=b"synthetic PDF revision one",
                    text=first_text,
                )
                before_observations = count("agenda_document_observations")
                merge(
                    historical,
                    historical_records,
                    historical_refs,
                    historical_run,
                    service.sink_id,
                )
                after_historical = next(
                    row
                    for row in api.get("/api/reviewer/staged-records").json()
                    if row["id"] == candidate_id
                )
                assert after_historical == current
                assert after_historical["review_notes"] == "Fixture location verified"
                assert api.get("/api/source-documents").json() == latest_document
                assert count("agenda_document_observations") == before_observations + 1
                assert count("agenda_candidate_revisions") == 2
                with SessionLocal() as session:
                    historical_public = session.scalar(
                        select(Phase3CollectionItem).where(
                            Phase3CollectionItem.collection_name == "development_records",
                            Phase3CollectionItem.item_id == public_id,
                        )
                    )
                    assert historical_public and historical_public.payload_json == persisted_public
                same_approval = api.post(
                    f"/api/reviewer/staged-records/{candidate_id}/approve",
                    json={
                        "notes": "Fixture location verified",
                        "expected_revision": current["state_revision"],
                    },
                )
                assert same_approval.status_code == 200, same_approval.text
                assert same_approval.json() == persisted_public

                third_run = "c04-third-" + uuid4().hex
                third, third_records, third_refs = setup_document(
                    service,
                    root,
                    run_id=third_run,
                    pdf=b"synthetic PDF revision three",
                    text=(
                        "1. SAMPLE RIDGE\nPreliminary (25 lots) Developer: Builder"
                        "\nLocated: West of Road"
                    ),
                )
                merge(third, third_records, third_refs, third_run, service.sink_id)
                third_observation = next(
                    row
                    for row in api.get("/api/reviewer/agenda-observations/unresolved").json()
                    if row["document_revision_id"] not in {observation["document_revision_id"]}
                )
                current = next(
                    row
                    for row in api.get("/api/reviewer/staged-records").json()
                    if row["id"] == candidate_id
                )
                third_link = api.post(
                    f"/api/reviewer/agenda-observations/{third_observation['id']}/resolve",
                    json={
                        "candidate_id": candidate_id,
                        "expected_observation_revision": 1,
                        "expected_candidate_revision": current["state_revision"],
                        "reason": "Reviewed third source case continuity",
                    },
                )
                assert third_link.status_code == 200, third_link.text
                with SessionLocal.begin() as session:
                    with CollectionUnitOfWork(session).canonical_mutation() as uow:
                        pending = uow.get_phase3("agenda_staged_records", candidate_id)
                        assert pending
                        pending["geometry"] = {"type": "Point", "coordinates": [-86.58, 34.73]}
                        pending["geometry_source"] = "reviewer-verified synthetic fixture"
                        pending["geometry_confidence"] = "high"
                        pending["location_required"] = False
                        pending["state_revision"] += 1
                        uow.upsert_phase3("agenda_staged_records", candidate_id, pending)
                changed_approval = api.post(
                    f"/api/reviewer/staged-records/{candidate_id}/approve",
                    json={
                        "notes": "Changed source status",
                        "expected_revision": pending["state_revision"],
                    },
                )
                assert changed_approval.status_code == 409, changed_approval.text
                assert (
                    changed_approval.json()["detail"]["code"] == "agenda_publication_update_pending"
                )
                after_conflict = next(
                    row
                    for row in api.get("/api/reviewer/staged-records").json()
                    if row["id"] == candidate_id
                )
                assert after_conflict["review_status"] == "pending"
                with SessionLocal() as session:
                    actual = session.scalar(
                        select(Phase3CollectionItem).where(
                            Phase3CollectionItem.collection_name == "development_records",
                            Phase3CollectionItem.item_id == public_id,
                        )
                    )
                    assert actual and actual.payload_json == persisted_public
                original_document = next(
                    row for row in api.get("/api/source-documents").json() if row["url"] == URL
                )
                moved_run = "c04-moved-" + uuid4().hex
                moved_url = "https://example.test/c04/moved-agenda.pdf"
                moved, moved_records, moved_refs = setup_document(
                    service,
                    root,
                    run_id=moved_run,
                    pdf=b"synthetic PDF changed download URL",
                    text=changed_text,
                    url=moved_url,
                )
                before_documents = count("source_documents")
                merge(moved, moved_records, moved_refs, moved_run, service.sink_id)
                assert count("source_documents") == before_documents
                unresolved_doc = next(
                    row
                    for row in api.get("/api/reviewer/agenda-documents/unresolved").json()
                    if row["url"] == moved_url
                )
                stale_doc_link = api.post(
                    f"/api/reviewer/agenda-documents/{unresolved_doc['id']}/resolve",
                    json={
                        "document_id": original_document["id"],
                        "expected_observation_revision": 2,
                        "reason": "Verified changed meeting packet URL",
                    },
                )
                assert stale_doc_link.status_code == 409
                linked_doc = api.post(
                    f"/api/reviewer/agenda-documents/{unresolved_doc['id']}/resolve",
                    json={
                        "document_id": original_document["id"],
                        "expected_observation_revision": 1,
                        "reason": "Verified changed meeting packet URL",
                    },
                )
                assert linked_doc.status_code == 200, linked_doc.text
                assert linked_doc.json() == {
                    "document_id": original_document["id"],
                    "status": "retry_required",
                }
                merge(moved, moved_records, moved_refs, moved_run, service.sink_id)
                assert count("source_documents") == before_documents
                newest_run = "c04-newest-" + uuid4().hex
                newest, newest_records, newest_refs = setup_document(
                    service,
                    root,
                    run_id=newest_run,
                    pdf=b"synthetic unrelated May agenda",
                    text="1. OTHER RIDGE\nLayout (8 lots) Developer: Other Builder",
                    url="https://example.test/c04/may-agenda.pdf",
                    date="2026-05-26",
                )
                before_revisions = count("agenda_document_revisions")
                with patch(
                    "app.ingestion.agenda_store._merge_candidate",
                    side_effect=RuntimeError("injected candidate merge failure"),
                ):
                    try:
                        merge(newest, newest_records, newest_refs, newest_run, service.sink_id)
                    except RuntimeError as exc:
                        assert str(exc) == "injected candidate merge failure"
                    else:
                        raise AssertionError("mid-merge failure did not roll back")
                assert count("source_documents") == before_documents
                assert count("agenda_document_revisions") == before_revisions
                merge(newest, newest_records, newest_refs, newest_run, service.sink_id)
                assert count("source_documents") == before_documents + 1
                # The moved packet's unresolved item is outside this refresh;
                # both retained document and item issues must remain visible.
                unresolved_moved_run = "c04-unresolved-moved-" + uuid4().hex
                unresolved_moved, _, unresolved_moved_refs = setup_document(
                    service,
                    root,
                    run_id=unresolved_moved_run,
                    pdf=b"synthetic ambiguous URL",
                    text=changed_text,
                    url="https://example.test/c04/another-moved-agenda.pdf",
                )
                merge(
                    unresolved_moved,
                    [],
                    unresolved_moved_refs,
                    unresolved_moved_run,
                    service.sink_id,
                )
                merge(newest, newest_records, newest_refs, newest_run, service.sink_id)
                with SessionLocal() as session:
                    stored_health = session.scalar(
                        select(Phase3CollectionItem).where(
                            Phase3CollectionItem.collection_name == "agenda_health",
                            Phase3CollectionItem.item_id == SOURCE,
                        )
                    )
                    assert stored_health
                    assert stored_health.payload_json["status"] == "degraded"
                    assert stored_health.payload_json["identity_unresolved_count"] == 2
                    assert (
                        "agenda_identity_unresolved"
                        in stored_health.payload_json["validation_errors"]
                    )
                assert any(
                    row["id"] == original_document["id"]
                    for row in api.get("/api/source-documents").json()
                )
                # Resolve a genuinely renamed occurrence without another ingest.
                renamed_run = "c04-renamed-" + uuid4().hex
                renamed, renamed_records, renamed_refs = setup_document(
                    service,
                    root,
                    run_id=renamed_run,
                    pdf=b"synthetic renamed agenda",
                    text="1. DISTINCT MEADOW\nLayout (24 lots) Developer: Builder",
                )
                merge(renamed, renamed_records, renamed_refs, renamed_run, service.sink_id)
                rename_observation = next(
                    row
                    for row in api.get("/api/reviewer/agenda-observations/unresolved").json()
                    if row["source_excerpt"] == "Distinct Meadow"
                )
                current = next(
                    row
                    for row in api.get("/api/reviewer/staged-records").json()
                    if row["id"] == candidate_id
                )
                audited_id = _stable_id("duplicate", candidate_id, "c04-audited-public")
                audited = {
                    "id": audited_id,
                    "staged_record_id": candidate_id,
                    "staged_title": current["title"],
                    "candidate_public_id": "c04-audited-public",
                    "candidate_title": "Audited match",
                    "score": 1,
                    "reasons": [],
                    "decision": "confirmed",
                    "review_actor": "reviewer",
                }
                unrelated = {
                    **audited,
                    "id": "c04-unrelated-suggestion",
                    "staged_record_id": "unrelated-candidate",
                }
                with SessionLocal.begin() as session:
                    with CollectionUnitOfWork(session).canonical_mutation() as uow:
                        uow.upsert_phase3("duplicate_candidates", audited_id, audited)
                        uow.upsert_phase3("duplicate_candidates", unrelated["id"], unrelated)
                renamed_response = api.post(
                    f"/api/reviewer/agenda-observations/{rename_observation['id']}/resolve",
                    json={
                        "candidate_id": candidate_id,
                        "expected_observation_revision": 1,
                        "expected_candidate_revision": current["state_revision"],
                        "reason": "Reviewed renamed source case continuity",
                    },
                )
                assert renamed_response.status_code == 200, renamed_response.text
                with SessionLocal() as session:
                    uow = CollectionUnitOfWork(session)
                    assert uow.get_phase3("duplicate_candidates", processed_duplicate_id) is None
                    assert uow.get_phase3("duplicate_candidates", audited_id) == audited
                    assert uow.get_phase3("duplicate_candidates", unrelated["id"]) == unrelated
                    retained = {
                        name: uow.list_phase3(name)
                        for name in (
                            "source_documents",
                            "agenda_staged_records",
                            "agenda_candidate_revisions",
                            "agenda_decision_events",
                            "development_records",
                            "duplicate_candidates",
                        )
                    }
                    previous_health = uow.get_phase3("agenda_health", SOURCE)
                with (
                    patch("app.ingestion.agenda_pipeline.get_settings", return_value=settings),
                    patch(
                        "app.ingestion.agenda_pipeline._fetch_archive_html",
                        return_value=("<html>No documents available</html>", "httpx_archive"),
                    ),
                ):
                    empty_health = ingest_huntsville_agendas(data_dir=root, client=api)
                assert empty_health["status"] == "degraded"
                assert "agenda_no_documents" in empty_health["validation_errors"]
                with SessionLocal() as session:
                    uow = CollectionUnitOfWork(session)
                    for name, snapshot in retained.items():
                        assert uow.list_phase3(name) == snapshot
                    persisted = uow.get_phase3("agenda_health", SOURCE)
                    assert persisted == empty_health
                    assert persisted["identity_unresolved_count"] == 2
                    assert persisted["last_success_at"] == previous_health["last_success_at"]
                public_health = next(
                    row
                    for row in api.get("/api/source-health").json()["sources"]
                    if row["key"] == SOURCE
                )
                assert public_health["status"] == "degraded"
                assert "agenda_no_documents" in public_health["validation_errors"]
                assert public_health["last_attempt_at"] == empty_health["checked_at"]
                # Partial durability failure records latest health but activates no content.
                valid_run = "c04-partial-valid-" + uuid4().hex
                valid_doc, valid_records, valid_refs = setup_document(
                    service,
                    root,
                    run_id=valid_run,
                    pdf=b"synthetic partial valid document",
                    text="1. PARTIAL RIDGE\nLayout (10 lots) Developer: Builder",
                    url="https://example.test/c04/partial-valid.pdf",
                    date="2026-06-23",
                )

                def partial_parse(**kwargs):
                    if kwargs["url"].endswith("pending.pdf"):
                        raise ArtifactError("artifact_unavailable")
                    return valid_doc, valid_records, list(valid_refs)

                with (
                    patch("app.ingestion.agenda_pipeline.get_settings", return_value=settings),
                    patch(
                        "app.ingestion.agenda_pipeline._fetch_archive_html",
                        return_value=("<html>synthetic mixed archive</html>", "httpx_archive"),
                    ),
                    patch(
                        "app.ingestion.agenda_pipeline.discover_agenda_links",
                        return_value=[
                            AgendaLink(title="Valid", url="https://example.test/c04/valid.pdf"),
                            AgendaLink(title="Pending", url="https://example.test/c04/pending.pdf"),
                        ],
                    ),
                    patch("app.ingestion.agenda_pipeline._fetch_and_parse_document", partial_parse),
                ):
                    partial_health = ingest_huntsville_agendas(data_dir=root, client=api)
                assert partial_health["documents_seen"] == 1
                assert partial_health["status"] == "degraded"
                assert "artifact_unavailable" in partial_health["validation_errors"]
                with SessionLocal() as session:
                    uow = CollectionUnitOfWork(session)
                    for name, snapshot in retained.items():
                        assert uow.list_phase3(name) == snapshot
                    assert uow.get_phase3("agenda_health", SOURCE) == partial_health
                    assert partial_health["last_success_at"] == empty_health["last_success_at"]
                latest_public_health = next(
                    row
                    for row in api.get("/api/source-health").json()["sources"]
                    if row["key"] == SOURCE
                )
                assert latest_public_health["last_attempt_at"] == partial_health["checked_at"]
                assert latest_public_health["status"] == "degraded"

                dateless_run = "c04-dateless-" + uuid4().hex
                dateless, dateless_records, dateless_refs = setup_document(
                    service,
                    root,
                    run_id=dateless_run,
                    pdf=b"synthetic dateless historical packet",
                    text="1. DATELESS RIDGE\nLayout (5 lots) Developer: Builder",
                    url="https://example.test/c04/dateless.pdf",
                    date=None,
                )
                merge(dateless, dateless_records, dateless_refs, dateless_run, service.sink_id)
                dateless_candidate = next(
                    row
                    for row in api.get("/api/reviewer/staged-records").json()
                    if row["title"] == "Dateless Ridge"
                )
                rejected_dateless = api.post(
                    f"/api/reviewer/staged-records/{dateless_candidate['id']}/reject",
                    json={"expected_revision": 1, "notes": "Dateless source remains unverified"},
                )
                assert rejected_dateless.status_code == 200
                dateless_b_run = "c04-dateless-b-" + uuid4().hex
                dateless_b, _, dateless_b_refs = setup_document(
                    service,
                    root,
                    run_id=dateless_b_run,
                    pdf=b"synthetic dateless current packet",
                    text="No candidate item",
                    url=dateless["url"],
                    date=None,
                )
                merge(dateless_b, [], dateless_b_refs, dateless_b_run, service.sink_id)
                dateless_before = api.get("/api/source-documents").json()
                moved_run = "c04-dateless-moved-" + uuid4().hex
                moved_dateless, moved_records, moved_refs = setup_document(
                    service,
                    root,
                    run_id=moved_run,
                    pdf=b"synthetic dateless historical packet",
                    text="1. DATELESS RIDGE\nLayout (5 lots) Developer: Builder",
                    url="https://example.test/c04/dateless-moved.pdf",
                    date=None,
                )
                merge(moved_dateless, moved_records, moved_refs, moved_run, service.sink_id)
                assert api.get("/api/source-documents").json() == dateless_before
                after_dateless = next(
                    row
                    for row in api.get("/api/reviewer/staged-records").json()
                    if row["id"] == dateless_candidate["id"]
                )
                assert after_dateless == rejected_dateless.json()
                assert any(
                    row["url"] == moved_dateless["url"]
                    for row in api.get("/api/reviewer/agenda-documents/unresolved").json()
                )
                # Existing processed ownership must survive agenda approval.
                for ownership in ("processed", "changed", "ambiguous"):
                    owned_id = f"c04-owned-{ownership}"
                    staged_id = f"agenda-{owned_id}"
                    with SessionLocal.begin() as session:
                        with CollectionUnitOfWork(session).canonical_mutation() as uow:
                            fixture = copy.deepcopy(
                                uow.get_phase3("agenda_staged_records", candidate_id)
                            )
                            assert fixture is not None
                            snapshot = copy.deepcopy(persisted_public)
                            snapshot["public_id"] = owned_id
                            fixture.update(id=staged_id, state_revision=1, review_status="pending")
                            fixture["publish_record"] = copy.deepcopy(snapshot)
                            fixture["geometry"] = copy.deepcopy(snapshot["geometry"])
                            fixture["centroid"] = snapshot["centroid"]
                            fixture["geometry_source"] = snapshot["geometry_source"]
                            fixture["geometry_confidence"] = snapshot["geometry_confidence"]
                            if ownership == "changed":
                                fixture["publish_record"]["title"] = "Changed owned publication"
                            uow.upsert_processed("development_records", owned_id, snapshot)
                            if ownership == "ambiguous":
                                uow.upsert_phase3("development_records", owned_id, snapshot)
                            uow.upsert_phase3("agenda_staged_records", staged_id, fixture)
                    events_before = count("agenda_decision_events")
                    versions_before = count("record_versions")
                    changes_before = count("change_log")
                    decision = api.post(
                        f"/api/reviewer/staged-records/{staged_id}/approve",
                        json={"expected_revision": 1, "notes": "Ownership fixture"},
                    )
                    assert decision.status_code == (200 if ownership == "processed" else 409), (
                        decision.text
                    )
                    if ownership != "processed":
                        expected_code = (
                            "agenda_identity_conflict"
                            if ownership == "ambiguous"
                            else "agenda_publication_update_pending"
                        )
                        assert decision.json()["detail"]["code"] == expected_code
                    with SessionLocal() as session:
                        uow = CollectionUnitOfWork(session)
                        assert uow.get_processed("development_records", owned_id) == snapshot
                        assert uow.get_phase3("development_records", owned_id) == (
                            snapshot if ownership == "ambiguous" else None
                        )
                        retained_candidate = uow.get_phase3("agenda_staged_records", staged_id)
                        assert retained_candidate is not None
                        assert retained_candidate["state_revision"] == (
                            2 if ownership == "processed" else 1
                        )
                    assert count("agenda_decision_events") == events_before + (
                        ownership == "processed"
                    )
                    assert count("record_versions") == versions_before
                    assert count("change_log") == changes_before
                result.write_text(
                    json.dumps(
                        {
                            "pending_text_rollback": True,
                            "same_revision_decision_retained": True,
                            "changed_unanchored_quarantined": True,
                            "stale_decision_and_resolution_409": True,
                            "resolved_revision_pending_then_one_publication": True,
                            "same_approval_returns_persisted_snapshot": True,
                            "historical_replay_preserves_latest_decision_and_publication": True,
                            "limited_refresh_retains_unresolved_document_and_item_health": True,
                            "changed_second_approval_defers_to_c06": True,
                            "changed_url_requires_audited_alias": True,
                            "mid_merge_failure_rolled_back_and_older_document_remained": True,
                            "processed_public_duplicate_detected": True,
                            "resolution_refreshes_system_duplicates_only": True,
                            "empty_discovery_health_persisted_content_retained": True,
                            "partial_durability_failure_health_only": True,
                            "dateless_moved_historical_packet_quarantined": True,
                            "processed_public_ownership_retained_on_identical_approval": True,
                            "changed_processed_publication_defers_to_c06": True,
                            "ambiguous_public_store_ownership_refused": True,
                            "first_document_id": first["id"],
                            "first_pdf_sha256": first["sha256"],
                            "second_pdf_sha256": changed["sha256"],
                        },
                        indent=2,
                    )
                )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-url", required=True)
    parser.add_argument("--reviewer-token", required=True)
    parser.add_argument("--result", type=Path, required=True)
    args = parser.parse_args()
    run(args.api_url, args.reviewer_token, args.result)
