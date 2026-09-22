"""Real PostgreSQL/HTTP acceptance checks for C03 source identity batches."""

from __future__ import annotations

import argparse
import json
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from sqlalchemy import delete, select, text

from app.db import SessionLocal
from app.ingestion.source_backfill import (
    apply_source_identity_backfill,
    dry_run_source_identity_backfill,
    export_source_identity_mapping,
)
from app.ingestion.source_merge import Coverage, SourceBatch, SourceRecord, merge_postgres_batch
from app.ingestion.pipeline import _quarantine_duplicate_source_records
from app.ingestion.sources.huntsville import NEW_SUBDIVISIONS
from app.models import ProcessedCollectionItem, SourceIdentityRegistry, SourceIngestionBatch, SourceObservation
from app.transactional_store import CollectionUnitOfWork


def record(*, title: str, checked: str = "2026-09-20", status: str = "layout") -> dict:
    return {
        "public_id": "new-unstable-id",
        "title": title,
        "description": "A source record",
        "development_type": "subdivision",
        "status": status,
        "source_status": status,
        "source_url": NEW_SUBDIVISIONS.layer_url,
        "source_agency": "Integration source",
        "date_discovered": "2025-01-02",
        "date_last_checked": checked,
        "review_status": "published",
        "geometry_source": "fixture",
        "geometry_confidence": "high",
        "confidence_level": "high",
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[-86.7, 34.6], [-86.6, 34.6], [-86.6, 34.7], [-86.7, 34.6]]],
        },
        "centroid": [-86.65, 34.65],
        "area_sq_m": 1.0,
        "address": None,
        "parcel_ids": [],
        "source_fields": {"SubdID": "001", "Subdivision": title},
        "proximity_flags": [],
    }


def staged() -> dict:
    return {
        "id": "stage-new-unstable-id",
        "raw_record_id": "001",
        "source_key": NEW_SUBDIVISIONS.key,
        "source_url": NEW_SUBDIVISIONS.layer_url,
        "title": "Changed title",
        "description": "A source record",
        "development_type": "subdivision",
        "source_status": "preliminary",
        "normalized_status": "preliminary",
        "source_agency": "Integration source",
        "date_discovered": "2025-01-02",
        "review_status": "approved",
        "record_confidence": "high",
        "geometry_source": "fixture",
        "geometry_confidence": "high",
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[-86.7, 34.6], [-86.6, 34.6], [-86.6, 34.7], [-86.7, 34.6]]],
        },
        "source_payload": {"SubdID": "001"},
        "normalization_notes": "Integration fixture.",
    }


def request_submission(api_url: str) -> tuple[int, dict]:
    payload = {
        "title": "C03 concurrent submission",
        "notes": "Real HTTP writer check while a source merge owns the pilot lock.",
        "source_url": "https://example.test/c03",
        "submitter_contact": "c03@example.test",
    }
    request = Request(
        f"{api_url}/api/public-submissions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=15) as response:  # noqa: S310 -- local integration gateway
        return response.status, json.loads(response.read())


def submission_result(api_url: str) -> tuple[int, dict]:
    try:
        return request_submission(api_url)
    except HTTPError as error:
        return error.code, json.loads(error.read())


def require_bookmarked_record(api_url: str) -> None:
    with urlopen(f"{api_url}/api/development-records/bookmarked-legacy-id", timeout=15) as response:  # noqa: S310
        payload = json.loads(response.read())
    if response.status != 200 or payload.get("public_id") != "bookmarked-legacy-id":
        raise AssertionError(f"bookmarked record URL no longer resolves: {payload!r}")


def seed_legacy() -> None:
    with SessionLocal.begin() as session:
        unit = CollectionUnitOfWork(session)
        with unit.canonical_mutation():
            for collection in ("development_records", "staged_development_records", "source_health"):
                session.execute(
                    delete(ProcessedCollectionItem).where(
                        ProcessedCollectionItem.collection_name == collection
                    )
                )
            # This manual row cites the official URL.  It must neither be
            # backfilled nor block future source rows.
            manual = record(title="Manual citation", status="proposed")
            manual.update({
                "public_id": "manual-citation",
                "development_type": "public_submission",
                "source_status": "submitted",
                "date_discovered": "2025-01-01",
                "date_last_checked": "2025-01-01",
                "source_fields": {},
            })
            unit.upsert_processed("development_records", "manual-citation", manual)
            legacy = record(title="Original title")
            legacy["public_id"] = "bookmarked-legacy-id"
            unit.upsert_processed("development_records", "bookmarked-legacy-id", legacy)


def merge_batch(
    *, run_id: str, coverage: Coverage | None, records: tuple[SourceRecord, ...],
    scope_id: str = "fixture-scope", outcome: str = "success", quarantined_count: int = 0,
    unit_of_work: CollectionUnitOfWork | None = None, session: object | None = None,
) -> dict:
    batch = SourceBatch(
        run_id=run_id, source_key=NEW_SUBDIVISIONS.key, scope_id=scope_id, scope_version="v1",
        checked_at=datetime(2026, 9, 20, tzinfo=UTC), records=records, coverage=coverage,
        outcome=outcome, quarantined_count=quarantined_count,  # type: ignore[arg-type]
    )
    if session is not None:
        return merge_postgres_batch(session, batch, unit_of_work=unit_of_work)  # type: ignore[arg-type]
    with SessionLocal.begin() as session:
        return merge_postgres_batch(session, batch)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-url", required=True)
    parser.add_argument("--result", type=Path, required=True)
    args = parser.parse_args()
    seed_legacy()

    with SessionLocal.begin() as session:
        unit = CollectionUnitOfWork(session)
        duplicate_legacy = record(title="Intentional duplicate legacy")
        duplicate_legacy["public_id"] = "duplicate-legacy-id"
        unit.upsert_processed("development_records", "duplicate-legacy-id", duplicate_legacy)
        refused = dry_run_source_identity_backfill(session)
        if not any(item["code"] == "ambiguous_anchor" for item in refused["diagnostics"]):
            raise AssertionError(f"duplicate legacy source anchor was not diagnosed: {refused!r}")
        try:
            apply_source_identity_backfill(session, expected_digest=str(refused["digest"]))
        except ValueError:
            pass
        else:
            raise AssertionError("ambiguous backfill unexpectedly applied mappings")
        if export_source_identity_mapping(session):
            raise AssertionError("refused backfill changed registry mappings")
        unit.delete_processed("development_records", "duplicate-legacy-id")
        report = dry_run_source_identity_backfill(session)
        if report["candidate_count"] != 1 or report["diagnostic_count"] != 0:
            raise AssertionError(f"unexpected backfill report: {report!r}")
        if report["skipped"] != [{"code": "out_of_scope_record", "public_id": "manual-citation"}]:
            raise AssertionError(f"manual source citation was not skipped: {report!r}")
        applied = apply_source_identity_backfill(session, expected_digest=str(report["digest"]))
        if applied["applied"] != 1:
            raise AssertionError(f"backfill did not apply: {applied!r}")

    changed = record(title="Changed title", status="preliminary")
    changed["public_id"] = "new-unstable-id"
    source_record = SourceRecord("001", "new-unstable-id", changed, staged())
    merged = merge_batch(run_id="c03-first", coverage=None, records=(source_record,))
    replay = merge_batch(run_id="c03-first", coverage=None, records=(source_record,))
    partial = merge_batch(run_id="c03-partial", coverage="partial", records=())
    failed = merge_batch(run_id="c03-failed", coverage=None, records=(), outcome="failed")
    different_scope = merge_batch(
        run_id="c03-other-scope", coverage="complete", records=(), scope_id="other-scope"
    )
    quarantined = merge_batch(
        run_id="c03-quarantined", coverage="complete", records=(), quarantined_count=1
    )
    complete = merge_batch(run_id="c03-complete", coverage="complete", records=())

    appended_payload = record(title="Appended source anchor")
    appended_payload["public_id"] = "new-anchor-002"
    appended_payload["source_fields"] = {"SubdID": "002", "Subdivision": "Appended source anchor"}
    appended_staged = {**staged(), "id": "stage-new-anchor-002", "raw_record_id": "002"}
    appended = merge_batch(
        run_id="c03-appended", coverage="partial",
        records=(SourceRecord("002", "new-anchor-002", appended_payload, appended_staged),),
    )

    duplicate_health = [{"key": NEW_SUBDIVISIONS.key, "source_url": NEW_SUBDIVISIONS.layer_url, "error_count": 0, "validation_errors": []}]
    duplicate_one = record(title="Unsafe duplicate one")
    duplicate_one["public_id"] = "unsafe-duplicate-one"
    duplicate_two = record(title="Unsafe duplicate two")
    duplicate_two["public_id"] = "unsafe-duplicate-two"
    duplicate_staged_one = {**staged(), "id": "stage-unsafe-duplicate-one"}
    duplicate_staged_two = {**staged(), "id": "stage-unsafe-duplicate-two"}
    safe_staged, safe_published = _quarantine_duplicate_source_records(
        [duplicate_staged_one, duplicate_staged_two], [duplicate_one, duplicate_two], duplicate_health
    )
    if safe_staged or safe_published or not duplicate_health[0]["validation_errors"]:
        raise AssertionError("duplicate source input was not fully quarantined")
    duplicate_batch = merge_batch(
        run_id="c03-duplicate-input", coverage="complete", records=(), quarantined_count=1
    )

    submission_results: list[tuple[int, dict]] = []
    thread = threading.Thread(target=lambda: submission_results.append(submission_result(args.api_url)))
    with SessionLocal.begin() as locked_session:
        locked_unit = CollectionUnitOfWork(locked_session)
        with locked_unit.canonical_mutation():
            thread.start()
            deadline = time.monotonic() + 1.2
            waiting = False
            while time.monotonic() < deadline:
                with SessionLocal() as observer:
                    waiting = bool(observer.scalar(text("SELECT EXISTS (SELECT 1 FROM pg_locks WHERE locktype = 'advisory' AND granted = false)")))
                if waiting:
                    break
                time.sleep(0.02)
            if not waiting:
                raise AssertionError("HTTP submission never waited on the held C02 advisory lock")
            concurrent = merge_batch(
                run_id="c03-concurrent", coverage="partial", records=(source_record,),
                session=locked_session, unit_of_work=locked_unit,
            )
    thread.join(timeout=20)
    if thread.is_alive():
        raise AssertionError("concurrent public submission did not complete")
    if not submission_results:
        raise AssertionError("concurrent public submission did not report a result")
    initial_submission = submission_results[0]
    if initial_submission[0] == 503:
        if initial_submission[1].get("detail", {}).get("code") != "transaction_busy":
            raise AssertionError(f"unexpected concurrent 503: {initial_submission!r}")
        final_submission = submission_result(args.api_url)
    else:
        final_submission = initial_submission
    if final_submission[0] != 200:
        raise AssertionError(f"submission did not succeed after lock release: {final_submission!r}")
    require_bookmarked_record(args.api_url)

    with SessionLocal() as session:
        unit = CollectionUnitOfWork(session)
        canonical = unit.get_processed("development_records", "bookmarked-legacy-id")
        if canonical is None:
            raise AssertionError("legacy bookmarked public ID disappeared")
        if canonical["date_discovered"] != "2025-01-02" or canonical["title"] != "Changed title":
            raise AssertionError(f"source update did not preserve ID/discovery date: {canonical!r}")
        batches = session.scalars(select(SourceIngestionBatch).order_by(SourceIngestionBatch.id)).all()
        observations = session.scalars(select(SourceObservation).order_by(SourceObservation.id)).all()
        mapping = export_source_identity_mapping(session)
        submissions = unit.list_phase3("public_submissions")
        registry = session.scalar(
            select(SourceIdentityRegistry).where(SourceIdentityRegistry.public_id == "bookmarked-legacy-id")
        )
    if registry is None or registry.source_record_id != "001":
        raise AssertionError("registry did not preserve the legacy public ID")
    if not any(item.get("title") == "C03 concurrent submission" for item in submissions):
        raise AssertionError("source merge and concurrent HTTP submission did not both persist")
    if merged["replayed"] or not replay["replayed"] or partial["source_missing"] != 0:
        raise AssertionError("replay/partial batch semantics are incorrect")
    if complete["source_missing"] != 1:
        raise AssertionError("explicit complete empty batch did not mark prior scoped source observed row missing")
    if failed["source_missing"] or different_scope["source_missing"] or quarantined["source_missing"] or duplicate_batch["source_missing"]:
        raise AssertionError("failed, scope-mismatched, or quarantined batch marked source rows missing")
    if appended["observed"] != 1:
        raise AssertionError("new stable source anchor could not append after reviewed backfill")
    if not any(batch.coverage == "unknown" for batch in batches):
        raise AssertionError("omitted legacy coverage did not persist as unknown")

    args.result.parent.mkdir(parents=True, exist_ok=True)
    args.result.write_text(json.dumps({
        "backfill_digest": report["digest"],
        "mapping": mapping,
        "bookmarked_record": {
            "public_id": canonical["public_id"],
            "date_discovered": canonical["date_discovered"],
            "title": canonical["title"],
        },
        "batch_coverages": [batch.coverage for batch in batches],
        "observations": [{"state": row.state, "fingerprint": row.content_fingerprint} for row in observations],
        "results": {
            "first": merged,
            "replay": replay,
            "partial": partial,
            "failed": failed,
            "different_scope": different_scope,
            "quarantined": quarantined,
            "duplicate_input": duplicate_batch,
            "appended": appended,
            "complete": complete,
            "concurrent": concurrent,
            "concurrent_submission_initial": initial_submission[0],
            "concurrent_submission_final": final_submission[0],
            "concurrent_waiting_lock_observed": True,
        },
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
