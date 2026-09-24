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

import httpx
from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError

from app.db import SessionLocal
from app.ingestion.connectors.arcgis import ArcGISRestConnector
from app.ingestion.pipeline import (
    _quarantine_duplicate_source_records,
    _write_postgres_source_state,
    ingest_madison_county,
)
from app.ingestion.source_backfill import (
    apply_source_identity_backfill,
    dry_run_source_identity_backfill,
    export_source_identity_mapping,
)
from app.ingestion.source_merge import (
    Coverage,
    PublicIdCollisionError,
    SourceBatch,
    SourceRecord,
    merge_postgres_batch,
)
from app.ingestion.sources.huntsville import NEW_SUBDIVISIONS
from app.map_layer_catalog import catalog_revision
from app.models import (
    ProcessedCollectionItem,
    SourceIdentityRegistry,
    SourceIngestionBatch,
    SourceObservation,
)
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


def madison_arcgis_handler(request: httpx.Request) -> httpx.Response:
    params = request.url.params
    if request.url.path.endswith("/0") and params.get("f") == "json":
        return httpx.Response(
            200,
            json={
                "currentVersion": 11.3,
                "geometryType": "esriGeometryPolygon",
                "supportedQueryFormats": "JSON, geoJSON",
            },
        )
    if params.get("returnCountOnly") == "true":
        return httpx.Response(200, json={"count": 4})
    valid_feature = {
        "type": "Feature",
        "properties": {
            "OBJECTID": 7,
            "Subd_ID": 95,
            "Subd_Name": "C03 Madison Fixture",
            "Parcels": "8",
            "YearFiled": 1987,
            "DateFiled": "6/24/1987",
        },
        "geometry": {
            "type": "Polygon",
            "coordinates": [
                [
                    [-86.72, 34.72],
                    [-86.71, 34.72],
                    [-86.71, 34.73],
                    [-86.72, 34.73],
                    [-86.72, 34.72],
                ]
            ],
        },
    }
    duplicate_feature = {
        **valid_feature,
        "properties": {**valid_feature["properties"], "OBJECTID": 8, "Subd_ID": 96},
    }
    missing_id_feature = {
        **valid_feature,
        "properties": {"OBJECTID": 9, "Subd_Name": "Missing source ID"},
    }
    return httpx.Response(
        200,
        json={
            "type": "FeatureCollection",
            "features": [
                valid_feature,
                duplicate_feature,
                duplicate_feature,
                missing_id_feature,
            ],
            "exceededTransferLimit": False,
        },
    )


def madison_quarantine_only_handler(request: httpx.Request) -> httpx.Response:
    response = madison_arcgis_handler(request)
    if request.url.path.endswith("/0") and request.url.params.get("f") == "json":
        return response
    if request.url.params.get("returnCountOnly") == "true":
        return httpx.Response(200, json={"count": 3})
    payload = response.json()
    payload["features"] = payload["features"][1:]
    return httpx.Response(200, json=payload)


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
            for collection in (
                "development_records",
                "staged_development_records",
                "source_health",
            ):
                session.execute(
                    delete(ProcessedCollectionItem).where(
                        ProcessedCollectionItem.collection_name == collection
                    )
                )
            # This manual row cites the official URL.  It must neither be
            # backfilled nor block future source rows.
            manual = record(title="Manual citation", status="proposed")
            manual.update(
                {
                    "public_id": "manual-citation",
                    "development_type": "public_submission",
                    "source_status": "submitted",
                    "date_discovered": "2025-01-01",
                    "date_last_checked": "2025-01-01",
                    "source_fields": {},
                }
            )
            unit.upsert_processed("development_records", "manual-citation", manual)
            legacy = record(title="Original title")
            legacy["public_id"] = "bookmarked-legacy-id"
            unit.upsert_processed("development_records", "bookmarked-legacy-id", legacy)


def merge_batch(
    *,
    run_id: str,
    coverage: Coverage | None,
    records: tuple[SourceRecord, ...],
    scope_id: str = "fixture-scope",
    outcome: str = "success",
    quarantined_count: int = 0,
    unit_of_work: CollectionUnitOfWork | None = None,
    session: object | None = None,
) -> dict:
    batch = SourceBatch(
        run_id=run_id,
        source_key=NEW_SUBDIVISIONS.key,
        scope_id=scope_id,
        scope_version="v1",
        checked_at=datetime(2026, 9, 20, tzinfo=UTC),
        records=records,
        coverage=coverage,
        outcome=outcome,
        quarantined_count=quarantined_count,  # type: ignore[arg-type]
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
    ready_layer = {
        "id": "wetlands",
        "kind": "vector",
        "title": "Wetlands",
        "category": "context",
        "data_version": "ready-data",
        "display_version": "ready-display",
        "delivery_status": "ready",
        "tile_url": "https://tiles.example/ready",
        "source_layer": "wetlands",
        "minzoom": 1,
        "maxzoom": 14,
        "bounds": [-87.0, 34.0, -86.0, 35.0],
        "coverage": {
            "status": "unknown",
            "scope_id": None,
            "reported_count": 1,
            "fetched_count": 1,
        },
        "source_name": "Agency",
        "source_url": "https://example.test/failed-environment",
        "attribution": "Agency",
        "caveat": "",
        "data_as_of": None,
        "fetched_at": "2026-09-20T00:00:00+00:00",
        "default_visible": True,
    }
    ready_catalog = {"data_mode": "live", "catalog_revision": "", "layers": [ready_layer]}
    ready_catalog["catalog_revision"] = catalog_revision(
        {"data_mode": "live", "layers": [ready_layer]}
    )
    with SessionLocal.begin() as session:
        unit = CollectionUnitOfWork(session)
        with unit.canonical_mutation():
            unit.upsert_processed("map_layer_catalog", "latest", ready_catalog)

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
        session.add(
            SourceIdentityRegistry(
                source_key="unrelated_source",
                source_record_id="other-anchor",
                public_id="bookmarked-legacy-id",
                first_discovered_at=datetime(2026, 9, 20, tzinfo=UTC),
            )
        )
        session.flush()
        reverse_conflict = dry_run_source_identity_backfill(session)
        if not any(
            item["code"] == "public_id_registry_conflict"
            for item in reverse_conflict["diagnostics"]
        ):
            raise AssertionError("backfill ignored a public ID owned by another registry anchor")
        try:
            apply_source_identity_backfill(session, expected_digest=str(reverse_conflict["digest"]))
        except ValueError:
            pass
        else:
            raise AssertionError("backfill applied a reverse public-ID collision")
        if export_source_identity_mapping(session) != [
            {
                "source_key": "unrelated_source",
                "source_record_id": "other-anchor",
                "public_id": "bookmarked-legacy-id",
            }
        ]:
            raise AssertionError("refused reverse-collision backfill partially changed mappings")
        session.execute(
            delete(SourceIdentityRegistry).where(
                SourceIdentityRegistry.source_key == "unrelated_source",
                SourceIdentityRegistry.source_record_id == "other-anchor",
            )
        )
        report = dry_run_source_identity_backfill(session)
        if report["candidate_count"] != 1 or report["diagnostic_count"] != 0:
            raise AssertionError(f"unexpected backfill report: {report!r}")
        if report["skipped"] != [{"code": "out_of_scope_record", "public_id": "manual-citation"}]:
            raise AssertionError(f"manual source citation was not skipped: {report!r}")
        applied = apply_source_identity_backfill(session, expected_digest=str(report["digest"]))
        if applied["applied"] != 1:
            raise AssertionError(f"backfill did not apply: {applied!r}")

    try:
        with SessionLocal.begin() as session:
            session.add(
                SourceIdentityRegistry(
                    source_key="unrelated_source",
                    source_record_id="unique-constraint-check",
                    public_id="bookmarked-legacy-id",
                    first_discovered_at=datetime(2026, 9, 20, tzinfo=UTC),
                )
            )
            session.flush()
    except IntegrityError:
        pass
    else:
        raise AssertionError("database allowed two registry owners for one public ID")

    manual_collision = SourceRecord(
        "new-manual-collision",
        "manual-citation",
        record(title="Cannot replace manual record"),
        {**staged(), "id": "stage-manual-citation"},
    )
    try:
        merge_batch(run_id="c03-manual-collision", coverage="partial", records=(manual_collision,))
    except PublicIdCollisionError:
        pass
    else:
        raise AssertionError("new source anchor replaced an unrelated manual public ID")
    with SessionLocal() as session:
        unit = CollectionUnitOfWork(session)
        manual_record = unit.get_processed("development_records", "manual-citation")
        if manual_record is None or manual_record["title"] != "Manual citation":
            raise AssertionError("colliding source batch changed the manual record")
        if session.scalar(
            select(SourceIngestionBatch).where(
                SourceIngestionBatch.run_id == "c03-manual-collision"
            )
        ) is not None:
            raise AssertionError("refused source batch was partially committed")

    with SessionLocal.begin() as session:
        session.add(
            SourceIdentityRegistry(
                source_key="unrelated_source",
                source_record_id="other-anchor",
                public_id="registry-owned",
                first_discovered_at=datetime(2026, 9, 20, tzinfo=UTC),
            )
        )
    registry_collision = SourceRecord(
        "new-registry-collision",
        "registry-owned",
        record(title="Cannot claim registry mapping"),
        {**staged(), "id": "stage-registry-owned"},
    )
    try:
        merge_batch(
            run_id="c03-registry-collision", coverage="partial", records=(registry_collision,)
        )
    except PublicIdCollisionError:
        pass
    else:
        raise AssertionError("new source anchor claimed another registry mapping")
    with SessionLocal.begin() as session:
        if session.scalar(
            select(SourceIngestionBatch).where(
                SourceIngestionBatch.run_id == "c03-registry-collision"
            )
        ) is not None:
            raise AssertionError("registry collision left a committed batch")
        session.execute(
            delete(SourceIdentityRegistry).where(
                SourceIdentityRegistry.source_key == "unrelated_source",
                SourceIdentityRegistry.source_record_id == "other-anchor",
            )
        )

    changed = record(title="Changed title", status="preliminary")
    changed["public_id"] = "new-unstable-id"
    source_record = SourceRecord(
        "001", "new-unstable-id", changed, {**staged(), "date_discovered": "2026-09-20"}
    )
    merged = merge_batch(run_id="c03-first", coverage=None, records=(source_record,))
    replay = merge_batch(run_id="c03-first", coverage=None, records=(source_record,))
    partial = merge_batch(run_id="c03-partial", coverage="partial", records=())
    failed = merge_batch(run_id="c03-failed", coverage=None, records=(), outcome="failed")
    failed_quarantined = merge_batch(
        run_id="c03-failed-quarantined",
        coverage="failed",
        records=(),
        quarantined_count=1,
    )
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
        run_id="c03-appended",
        coverage="partial",
        records=(SourceRecord("002", "new-anchor-002", appended_payload, appended_staged),),
    )

    duplicate_health = [
        {
            "key": NEW_SUBDIVISIONS.key,
            "source_url": NEW_SUBDIVISIONS.layer_url,
            "error_count": 0,
            "validation_errors": [],
        }
    ]
    duplicate_one = record(title="Unsafe duplicate one")
    duplicate_one["public_id"] = "unsafe-duplicate-one"
    duplicate_two = record(title="Unsafe duplicate two")
    duplicate_two["public_id"] = "unsafe-duplicate-two"
    duplicate_staged_one = {**staged(), "id": "stage-unsafe-duplicate-one"}
    duplicate_staged_two = {**staged(), "id": "stage-unsafe-duplicate-two"}
    safe_staged, safe_published = _quarantine_duplicate_source_records(
        [duplicate_staged_one, duplicate_staged_two],
        [duplicate_one, duplicate_two],
        duplicate_health,
    )
    if (
        safe_staged
        or safe_published
        or not duplicate_health[0]["validation_errors"]
        or duplicate_health[0]["quarantined_count"] != 2
    ):
        raise AssertionError("duplicate source input was not fully quarantined")
    provisional_health = [
        {
            "key": NEW_SUBDIVISIONS.key,
            "source_url": NEW_SUBDIVISIONS.layer_url,
            "error_count": 0,
            "validation_errors": [],
        },
        {
            "key": "other_source",
            "source_url": "https://example.test/other-source",
            "error_count": 0,
            "validation_errors": [],
        },
    ]
    provisional_staged, provisional_published = _quarantine_duplicate_source_records(
        [
            {**staged(), "id": "stage-collision", "raw_record_id": "anchor-A"},
            {
                **staged(),
                "id": "stage-collision",
                "raw_record_id": "anchor-B",
                "source_key": "other_source",
            },
        ],
        [
            {**record(title="Anchor A"), "public_id": "collision"},
            {
                **record(title="Anchor B"),
                "public_id": "collision",
                "source_url": "https://example.test/other-source",
            },
        ],
        provisional_health,
    )
    if (
        provisional_staged
        or provisional_published
        or [item.get("quarantined_count") for item in provisional_health] != [1, 1]
        or not any(
            "duplicate provisional public ID" in error
            for health in provisional_health
            for error in health["validation_errors"]
        )
    ):
        raise AssertionError("distinct anchors with one provisional ID were coalesced")
    duplicate_batch = merge_batch(
        run_id="c03-duplicate-input", coverage="complete", records=(), quarantined_count=1
    )

    submission_results: list[tuple[int, dict]] = []
    thread = threading.Thread(
        target=lambda: submission_results.append(submission_result(args.api_url))
    )
    with SessionLocal.begin() as locked_session:
        locked_unit = CollectionUnitOfWork(locked_session)
        with locked_unit.canonical_mutation():
            thread.start()
            deadline = time.monotonic() + 1.2
            waiting = False
            while time.monotonic() < deadline:
                with SessionLocal() as observer:
                    waiting = bool(
                        observer.scalar(
                            text(
                                "SELECT EXISTS (SELECT 1 FROM pg_locks "
                                "WHERE locktype = 'advisory' AND granted = false)"
                            )
                        )
                    )
                if waiting:
                    break
                time.sleep(0.02)
            if not waiting:
                raise AssertionError("HTTP submission never waited on the held C02 advisory lock")
            concurrent = merge_batch(
                run_id="c03-concurrent",
                coverage="partial",
                records=(source_record,),
                session=locked_session,
                unit_of_work=locked_unit,
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

    # Exercise the actual production adapter, including its shared UoW writes,
    # instead of claiming coverage from direct merge-helper calls alone.
    with SessionLocal.begin() as session:
        unit = CollectionUnitOfWork(session)
        with unit.canonical_mutation():
            unit.upsert_processed(
                "environmental_overlays",
                "retained-overlay",
                {"id": "retained-overlay", "version": "good"},
            )
    adapter_health = _write_postgres_source_state(
        run_id="c03-adapter",
        checked_at="2026-09-20T00:00:00+00:00",
        source_health=[
            {
                "key": NEW_SUBDIVISIONS.key,
                "source_url": NEW_SUBDIVISIONS.layer_url,
                "status": "healthy",
                "error_count": 1,
                "validation_errors": ["identity_quarantined: duplicate source anchor"],
                "metadata": {"reported_count": 1, "fetched_count": 1},
            },
            {
                "key": "huntsville_usfws_wetlands",
                "source_url": "https://example.test/failed-environment",
                "status": "failing",
                "error_count": 1,
                "metadata": {},
            },
        ],
        raw_records=[
            {
                "data_source_key": "huntsville_usfws_wetlands",
                "source_record_id": None,
                "payload_json": {"private_raw": "retained only in raw evidence"},
                "payload_sha256": "c03-raw-environment-digest",
                "fetched_at": "2026-09-20T00:00:00+00:00",
            },
            {
                "data_source_key": NEW_SUBDIVISIONS.key,
                "source_record_id": "quarantined-duplicate",
                "payload_json": {"private_raw": "duplicate source anchor"},
                "payload_sha256": "c03-raw-duplicate-digest",
                "fetched_at": "2026-09-20T00:00:00+00:00",
            },
            {
                "data_source_key": NEW_SUBDIVISIONS.key,
                "source_record_id": "quarantined-duplicate",
                "payload_json": {"private_raw": "duplicate source anchor"},
                "payload_sha256": "c03-raw-duplicate-digest",
                "fetched_at": "2026-09-20T00:00:00+00:00",
            },
        ],
        staged_records=[],
        published_records=[],
        overlays=[
            {
                "id": "retained-overlay",
                "source_url": "https://example.test/failed-environment",
                "version": "bad",
            }
        ],
        catalog={
            "data_mode": "live",
            "catalog_revision": catalog_revision(
                {
                    "data_mode": "live",
                    "layers": [
                        {
                            **ready_layer,
                            "data_version": "failed",
                            "delivery_status": "failed",
                            "tile_url": None,
                        }
                    ],
                }
            ),
            "layers": [
                {
                    **ready_layer,
                    "data_version": "failed",
                    "delivery_status": "failed",
                    "tile_url": None,
                }
            ],
        },
    )
    madison_data_dir = Path("/tmp/c03-madison-artifacts")
    with ArcGISRestConnector(transport=httpx.MockTransport(madison_arcgis_handler)) as connector:
        madison_health = ingest_madison_county(
            data_dir=madison_data_dir,
            record_limit=1,
            connector=connector,
        )
    artifact_manifest = json.loads(
        (madison_data_dir / "processed" / "artifact_manifest.json").read_text(encoding="utf-8")
    )
    madison_artifact = next(
        item for item in artifact_manifest if item["source_key"] == "madison_county_subdivisions"
    )
    madison_source_health = next(
        item for item in madison_health["sources"] if item["key"] == "madison_county_subdivisions"
    )
    madison_raw_path = madison_data_dir / str(madison_artifact["local_path"])
    if (
        not madison_raw_path.is_file()
        or madison_artifact["byte_size"] != madison_raw_path.stat().st_size
        or madison_artifact["sha256"] != madison_source_health["raw_artifact_sha256"]
    ):
        raise AssertionError("Madison raw artifact manifest did not retain its byte/hash evidence")
    quarantine_transport = httpx.MockTransport(madison_quarantine_only_handler)
    with ArcGISRestConnector(transport=quarantine_transport) as connector:
        quarantine_only_health = ingest_madison_county(
            data_dir=madison_data_dir,
            record_limit=3,
            connector=connector,
        )
    quarantine_only_source = next(
        item
        for item in quarantine_only_health["sources"]
        if item["key"] == "madison_county_subdivisions"
    )
    if (
        quarantine_only_source["records_seen"] != 3
        or quarantine_only_source["records_created"] != 0
        or quarantine_only_health["batches"]["madison_county_subdivisions"]["source_missing"]
    ):
        raise AssertionError("quarantine-only Madison run reported accepted or missing records")
    with SessionLocal() as session:
        quarantined_batch = session.scalar(
            select(SourceIngestionBatch).where(
                SourceIngestionBatch.run_id == quarantine_only_health["run_id"],
                SourceIngestionBatch.source_key == "madison_county_subdivisions",
            )
        )
        if (
            quarantined_batch is None
            or quarantined_batch.counts_json["quarantined"] != 3
            or quarantined_batch.coverage != "partial"
        ):
            raise AssertionError("quarantine-only batch lost rejected input multiplicity")

    with SessionLocal() as session:
        unit = CollectionUnitOfWork(session)
        canonical = unit.get_processed("development_records", "bookmarked-legacy-id")
        if canonical is None:
            raise AssertionError("legacy bookmarked public ID disappeared")
        if canonical["date_discovered"] != "2025-01-02" or canonical["title"] != "Changed title":
            raise AssertionError(f"source update did not preserve ID/discovery date: {canonical!r}")
        staged_canonical = unit.get_processed(
            "staged_development_records", "stage-bookmarked-legacy-id"
        )
        if staged_canonical is None or staged_canonical["date_discovered"] != "2025-01-02":
            raise AssertionError("refreshed staged record advanced its original discovery date")
        batches = session.scalars(
            select(SourceIngestionBatch).order_by(SourceIngestionBatch.id)
        ).all()
        observations = session.scalars(
            select(SourceObservation).order_by(SourceObservation.id)
        ).all()
        mapping = export_source_identity_mapping(session)
        submissions = unit.list_phase3("public_submissions")
        registry = session.scalar(
            select(SourceIdentityRegistry).where(
                SourceIdentityRegistry.public_id == "bookmarked-legacy-id"
            )
        )
        raw = unit.get_processed(
            "raw_records",
            "huntsville_usfws_wetlands:c03-adapter:c03-raw-environment-digest:00000000",
        )
        raw_prefix = f"{NEW_SUBDIVISIONS.key}:c03-adapter:c03-raw-duplicate-digest"
        duplicate_raw_first = unit.get_processed("raw_records", f"{raw_prefix}:00000001")
        duplicate_raw_second = unit.get_processed("raw_records", f"{raw_prefix}:00000002")
        retained_overlay = unit.get_processed("environmental_overlays", "retained-overlay")
        manual = unit.get_processed("development_records", "manual-citation")
        madison_records = [
            item
            for item in unit.list_processed("development_records")
            if item.get("source_key") == "madison_county_subdivisions"
        ]
        merged_health = unit.get_processed("source_health", "latest")
        preserved_catalog = unit.get_processed("map_layer_catalog", "latest")
    if registry is None or registry.source_record_id != "001":
        raise AssertionError("registry did not preserve the legacy public ID")
    if not any(item.get("title") == "C03 concurrent submission" for item in submissions):
        raise AssertionError("source merge and concurrent HTTP submission did not both persist")
    if merged["replayed"] or not replay["replayed"] or partial["source_missing"] != 0:
        raise AssertionError("replay/partial batch semantics are incorrect")
    if complete["source_missing"] != 1:
        raise AssertionError(
            "explicit complete empty batch did not mark prior scoped source observed row missing"
        )
    if (
        failed["source_missing"]
        or failed_quarantined["source_missing"]
        or different_scope["source_missing"]
        or quarantined["source_missing"]
        or duplicate_batch["source_missing"]
    ):
        raise AssertionError(
            "failed, scope-mismatched, or quarantined batch marked source rows missing"
        )
    if appended["observed"] != 1:
        raise AssertionError("new stable source anchor could not append after reviewed backfill")
    if not any(batch.coverage == "unknown" for batch in batches):
        raise AssertionError("omitted legacy coverage did not persist as unknown")
    if not any(
        batch.run_id == "c03-failed-quarantined" and batch.coverage == "failed" for batch in batches
    ):
        raise AssertionError("explicit failed coverage was downgraded by quarantined input")
    if (
        raw is None
        or duplicate_raw_first is None
        or duplicate_raw_first != duplicate_raw_second
        or duplicate_raw_first["source_record_id"] != "quarantined-duplicate"
        or raw.get("ingestion_run_id") != "c03-adapter"
        or adapter_health["records"]["raw"] != 3
    ):
        raise AssertionError("adapter did not retain both identical quarantined raw observations")
    if retained_overlay != {"id": "retained-overlay", "version": "good"}:
        raise AssertionError("failed environmental source replaced the prior overlay")
    if manual is None or adapter_health["records"]["published"] < 2:
        raise AssertionError("adapter did not preserve manual/other canonical records")
    if not isinstance(preserved_catalog, dict) or preserved_catalog["layers"] != [ready_layer]:
        raise AssertionError("source refresh replaced a ready catalog layer")
    if {item["key"] for item in adapter_health["sources"]} != {
        NEW_SUBDIVISIONS.key,
        "huntsville_usfws_wetlands",
    }:
        raise AssertionError(f"adapter source-health merge is incomplete: {adapter_health!r}")
    if (
        len(madison_records) != 1
        or madison_records[0].get("source_record_id") != "95"
        or manual is None
        or not isinstance(merged_health, dict)
        or merged_health["records"]["raw"] < 7
        or merged_health["records"]["published"] < 4
    ):
        raise AssertionError(
            "real Madison PostgreSQL ingestion did not preserve source or other records"
        )
    if (
        madison_source_health["records_seen"] != 4
        or madison_source_health["records_created"] != 1
        or not any(
            "identity_quarantined" in error
            for error in madison_source_health["validation_errors"]
        )
    ):
        raise AssertionError("Madison health counted quarantined source rows as accepted")

    args.result.parent.mkdir(parents=True, exist_ok=True)
    args.result.write_text(
        json.dumps(
            {
                "backfill_digest": report["digest"],
                "mapping": mapping,
                "bookmarked_record": {
                    "public_id": canonical["public_id"],
                    "date_discovered": canonical["date_discovered"],
                    "title": canonical["title"],
                },
                "batch_coverages": [batch.coverage for batch in batches],
                "observations": [
                    {"state": row.state, "fingerprint": row.content_fingerprint}
                    for row in observations
                ],
                "results": {
                    "first": merged,
                    "replay": replay,
                    "partial": partial,
                    "failed": failed,
                    "failed_quarantined": failed_quarantined,
                    "different_scope": different_scope,
                    "quarantined": quarantined,
                    "duplicate_input": duplicate_batch,
                    "appended": appended,
                    "complete": complete,
                    "concurrent": concurrent,
                    "concurrent_submission_initial": initial_submission[0],
                    "concurrent_submission_final": final_submission[0],
                    "concurrent_waiting_lock_observed": True,
                    "adapter": {
                        "raw_retained": True,
                        "failed_overlay_skipped": True,
                        "manual_preserved": True,
                    },
                },
                "madison_postgres_driver": {
                    "raw_artifact_bytes": madison_artifact["byte_size"],
                    "raw_observations": merged_health["records"]["raw"],
                    "published": merged_health["records"]["published"],
                    "accepted_of_seen": [
                        madison_source_health["records_created"],
                        madison_source_health["records_seen"],
                    ],
                    "quarantine_only_accepted_of_seen": [
                        quarantine_only_source["records_created"],
                        quarantine_only_source["records_seen"],
                    ],
                },
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
