"""Real PostGIS/API acceptance for P03; only the runner's isolated database."""

from __future__ import annotations

import argparse
import copy
import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import httpx
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.db import SessionLocal
from app.ingestion import environmental_import as importer
from app.ingestion.environmental_import import ImportBusyError, ImportOptions, import_session
from app.ingestion.environmental_output import import_environmental_output
from app.ingestion.environmental_stream import (
    InputChangedError,
    inspect_overlay_file,
    stream_overlay_features,
)
from app.ingestion.pipeline import _write_postgres_source_state
from app.map_layer_catalog import _project_legacy_catalog, catalog_revision
from app.models import EnvironmentalLayer
from app.processed_store import read_processed_payload, write_processed_payload


def metadata() -> dict:
    return {
        "id": "p03-environment",
        "name": "P03 environmental fixture",
        "category": "wetlands",
        "source_url": "https://example.test/p03",
        "attribution": "Synthetic fixture",
        "caveat": "Fixture only",
        "geom_type": "polygon",
    }


def fixture() -> list[dict]:
    outer = [[-86.8, 34.7], [-86.6, 34.7], [-86.6, 34.9], [-86.8, 34.9], [-86.8, 34.7]]
    hole = [[-86.75, 34.75], [-86.75, 34.8], [-86.7, 34.8], [-86.7, 34.75], [-86.75, 34.75]]
    precise = -86.51234567890123
    tiny = [[precise, 34.7], [-86.5, 34.7], [-86.5, 34.71], [precise, 34.7]]
    shapes = [
        {"type": "Polygon", "coordinates": [outer, hole]},
        {"type": "MultiPolygon", "coordinates": [[tiny]]},
    ]
    return [
        {
            **metadata(),
            "features": {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "id": identity,
                        "geometry": shape,
                        "properties": {
                            "WETLAND_TYPE": "Synthetic",
                            "private_email": "private-p03@example.test",
                        },
                    }
                    for identity, shape in zip(["0001", 0], shapes, strict=True)
                ],
            },
        }
    ]


def geometry_indexes(session) -> list[dict]:
    return [
        dict(row._mapping)
        for row in session.execute(
            text("""
            SELECT indexname, indexdef FROM pg_indexes
            WHERE tablename='environmental_features' AND indexdef LIKE '%USING gist%'
            ORDER BY indexname
        """)
        )
    ]


def seed_legacy(output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    with SessionLocal.begin() as session:
        (output / "legacy-indexes.json").write_text(json.dumps(geometry_indexes(session)))
        layer_id = session.scalar(
            text("""
            INSERT INTO environmental_layers (name, category, source_url, geom_type)
            VALUES ('Legacy unmapped fixture', 'context', 'https://example.test/legacy', 'point')
            RETURNING id
        """)
        )
        for source_id in ("duplicate-legacy", "duplicate-legacy", None):
            session.execute(
                text("""
                INSERT INTO environmental_features
                    (environmental_layer_id, source_feature_id, geometry)
                VALUES (:layer, :source_id, ST_SetSRID(ST_MakePoint(-86.7, 34.7), 4326))
            """),
                {"layer": layer_id, "source_id": source_id},
            )


def counts() -> tuple[int, int]:
    with SessionLocal() as session:
        return tuple(
            session.execute(
                text("""
            SELECT (SELECT count(*) FROM environmental_layers),
                   (SELECT count(*) FROM environmental_features)
        """)
            ).one()
        )


def verify_snapshot(snapshot: Path) -> dict:
    """Inspect only a read-only disposable copy; never emit source exception text."""
    try:
        checksum, overlays = inspect_overlay_file(snapshot)
        reports = []
        for overlay in overlays:
            options = ImportOptions(
                overlay.metadata["id"], scope_id="copied-legacy-unknown", batch_size=16
            )
            before = counts()
            dry_run = importer.import_environmental_file(snapshot, options)
            assert counts() == before
            report = importer.import_environmental_file(snapshot, options, dry_run=False)
            assert tuple(report[key] for key in ("seen", "accepted", "rejected")) == tuple(
                dry_run[key] for key in ("seen", "accepted", "rejected")
            )
            samples = []
            stride = max(1, overlay.feature_count // 25)
            with SessionLocal() as session:
                for ordinal, feature in enumerate(
                    stream_overlay_features(
                        snapshot, index=overlay.index, expected_checksum=checksum
                    )
                ):
                    if ordinal % stride or len(samples) >= 25:
                        continue
                    try:
                        prepared = importer._prepare(feature, options)
                    except ValueError:
                        continue
                    row = session.execute(
                        text("""
                        SELECT ST_AsGeoJSON(f.geometry,17), f.import_fingerprint
                        FROM environmental_features f JOIN environmental_layers l
                          ON l.id=f.environmental_layer_id
                        WHERE l.layer_key=:layer AND l.data_version=:version
                          AND f.import_managed AND f.source_feature_id=:identity
                    """),
                        {
                            "layer": options.layer_id,
                            "version": report["data_version"],
                            "identity": prepared["source_id"],
                        },
                    ).one_or_none()
                    if row is None or row[1] != prepared["fingerprint"]:
                        continue  # Quarantined feature has no accepted corresponding geometry.
                    assert json.loads(row[0]) == json.loads(prepared["geometry"])
                    samples.append({"source_ordinal": ordinal, "coordinates_equal": True})
            reports.append(
                {
                    "input_feature_count": overlay.feature_count,
                    "dry_run": dry_run,
                    "import": report,
                    "geometry_samples": samples,
                    "sample_method": (
                        "at most 25 evenly spaced accepted source ordinals; "
                        "exact parsed coordinate equality"
                    ),
                }
            )
        assert inspect_overlay_file(snapshot)[0] == checksum
        return {"bytes": snapshot.stat().st_size, "sha256": checksum, "layers": reports}
    except Exception:
        raise RuntimeError("copied_snapshot_acceptance_failed") from None


def verify(api_url: str, output: Path, snapshot: Path | None = None) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    path = output / "synthetic-overlays.json"
    source = fixture()
    path.write_text(json.dumps(source), encoding="utf-8")
    checksum, _ = inspect_overlay_file(path)
    options = ImportOptions(
        "p03-environment", scope_id="synthetic", scope_version="1", batch_size=1
    )
    checks: list[str] = []
    with SessionLocal() as session:
        legacy = session.execute(
            text("""
            SELECT count(*), count(*) FILTER (WHERE import_managed)
            FROM environmental_features
        """)
        ).one()
        assert tuple(legacy) == (3, 0)
        indexes = session.execute(
            text("""
            SELECT indexname, indexdef FROM pg_indexes WHERE tablename='environmental_features'
        """)
        ).all()
        assert geometry_indexes(session) == json.loads((output / "legacy-indexes.json").read_text())
        assert any(row.indexname == "uq_environmental_managed_feature" for row in indexes)
    checks.append("additive-migration-preserves-legacy-duplicates-and-existing-gist-indexes")

    baseline = counts()
    dry_run = importer.import_environmental_file(path, options)
    assert dry_run["status"] == "validated" and dry_run["accepted"] == 2
    assert counts() == baseline
    checks.append("dry-run-does-not-write-imports")

    # A valid active catalog is unrelated to the pending shadow import.
    ready = _project_legacy_catalog([(metadata(), 2)]).model_dump(mode="json")
    ready["layers"][0].update(
        {
            "delivery_status": "ready",
            "data_version": "prior-data",
            "display_version": "prior-display",
            "tile_url": "/api/map/layers/p03-environment/tiles/prior-display/{z}/{x}/{y}.pbf",
            "source_layer": "environment",
            "minzoom": 8,
            "maxzoom": 18,
        }
    )
    ready["catalog_revision"] = catalog_revision(
        {
            "data_mode": ready["data_mode"],
            "layers": ready["layers"],
        }
    )
    write_processed_payload("map_layer_catalog", ready)
    try:
        importer.import_environmental_file(path, options, dry_run=False, fail_after_batches=1)
    except RuntimeError as exc:
        assert str(exc) == "injected_after_chunk"
    else:
        raise AssertionError("Expected injected interruption")
    with SessionLocal() as session:
        failed = session.scalar(
            select(EnvironmentalLayer).where(
                EnvironmentalLayer.data_version == importer.data_version(checksum, options),
            )
        )
        assert failed is not None and failed.import_status == "failed"
        assert failed.import_checkpoint == 1 and failed.accepted_count == 1
    resumed = importer.import_environmental_file(path, options, dry_run=False)
    assert resumed["status"] == "validated" and resumed["accepted"] == 2
    assert "failure" not in resumed["diagnostics"]
    after_resume = counts()
    replay = importer.import_environmental_file(path, options, dry_run=False)
    assert replay["replayed"] and counts() == after_resume
    checks.append("interruption-checkpoint-resume-and-idempotent-replay")
    with SessionLocal() as session:
        stored = session.scalar(
            select(EnvironmentalLayer).where(
                EnvironmentalLayer.data_version == resumed["data_version"]
            )
        )
        assert stored is not None and "failure" not in stored.diagnostics_json

    with SessionLocal() as session:
        rows = session.execute(
            text("""
            SELECT source_feature_id, ST_AsGeoJSON(geometry,17), attributes_json
            FROM environmental_features WHERE import_managed ORDER BY source_feature_id
        """)
        ).all()
        expected = {str(item["id"]): item["geometry"] for item in source[0]["features"]["features"]}
        for identity, geometry, attributes in rows:
            assert json.loads(geometry) == expected[identity]
            assert "private_email" not in attributes
        imported_layer = session.scalar(
            select(EnvironmentalLayer.id).where(
                EnvironmentalLayer.data_version == resumed["data_version"],
            )
        )
        for invalid_identity in ("0001", None, " "):
            try:
                with session.begin_nested():
                    session.execute(
                        text("""
                        INSERT INTO environmental_features
                            (environmental_layer_id, source_feature_id, geometry, import_managed)
                        VALUES (:layer, :identity, ST_SetSRID(ST_MakePoint(-86.7,34.7),4326), true)
                    """),
                        {"layer": imported_layer, "identity": invalid_identity},
                    )
            except IntegrityError:
                pass
            else:
                raise AssertionError("Managed feature identity constraint was not enforced")
    checks.append("original-hole-multipolygon-precision-and-public-attributes")

    # Kill a real owned import process only after its first committed checkpoint.
    marker = output / "committed-checkpoint"
    child_code = """
import sys, time
from pathlib import Path
from app.ingestion import environmental_import as module
original = module.update_import_progress
def pause(metadata, report):
    original(metadata, report)
    if report['checkpoint'] >= 1:
        Path(sys.argv[2]).write_text('committed')
        time.sleep(60)
module.update_import_progress = pause
module.import_environmental_file(Path(sys.argv[1]), module.ImportOptions(
    'p03-environment', scope_id='hard-kill', batch_size=1), dry_run=False)
"""
    child = subprocess.Popen(
        [sys.executable, "-c", child_code, str(path), str(marker)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 20
        while not marker.exists() and time.monotonic() < deadline and child.poll() is None:
            time.sleep(0.05)
        assert marker.exists(), "Child did not reach its committed checkpoint"
    finally:
        child.kill()
        child.wait(timeout=10)
    killed_resume = importer.import_environmental_file(
        path, ImportOptions(options.layer_id, scope_id="hard-kill", batch_size=1), dry_run=False
    )
    assert killed_resume["accepted"] == 2 and killed_resume["status"] == "validated"
    checks.append("hard-process-kill-releases-lock-and-resumes-committed-checkpoint")

    version = importer.data_version(checksum, options)
    with import_session(options.layer_id, version):
        try:
            importer.import_environmental_file(path, options, dry_run=False)
        except ImportBusyError:
            pass
        else:
            raise AssertionError("Same-version importer bypassed its session lock")
        other = ImportOptions(options.layer_id, scope_id="synthetic", scope_version="2")
        assert (
            importer.import_environmental_file(path, other, dry_run=False)["status"] == "validated"
        )
    try:
        with import_session("connection-death", "b" * 64) as locked:
            pid = locked.scalar(text("SELECT pg_backend_pid()"))
            locked.commit()
            with SessionLocal.begin() as killer:
                killer.execute(text("SELECT pg_terminate_backend(:pid)"), {"pid": pid})
            locked.execute(text("SELECT 1"))
    except SQLAlchemyError:
        pass
    with import_session("connection-death", "b" * 64):
        pass
    checks.append("same-version-lock-distinct-version-progress-and-connection-death-release")

    bad = copy.deepcopy(source)
    bad[0]["features"]["features"].extend(
        [
            copy.deepcopy(bad[0]["features"]["features"][0]),
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [1, 2]}},
            {
                "type": "Feature",
                "id": "wrong-family",
                "geometry": {"type": "Point", "coordinates": [1, 2]},
            },
            {
                "type": "Feature",
                "id": "bowtie",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [-86.8, 34.7],
                            [-86.6, 34.9],
                            [-86.6, 34.7],
                            [-86.8, 34.9],
                            [-86.8, 34.7],
                        ]
                    ],
                },
                "properties": {},
            },
        ]
    )
    conflicting = copy.deepcopy(bad[0]["features"]["features"][0])
    conflicting["properties"]["WETLAND_TYPE"] = "Conflicting observation"
    bad[0]["features"]["features"].append(conflicting)
    bad_path = output / "quarantined-overlays.json"
    bad_path.write_text(json.dumps(bad))
    rejected = importer.import_environmental_file(bad_path, options, dry_run=False)
    assert rejected["status"] == "failed" and rejected["rejected"] == 5
    assert rejected["diagnostics"]["reasons"]["geometry_family_mismatch"] == 1
    assert rejected["duplicates"] == 2 and rejected["coverage"] == "partial"
    with SessionLocal() as session:
        stored = session.scalar(
            select(EnvironmentalLayer).where(
                EnvironmentalLayer.data_version == rejected["data_version"]
            )
        )
        assert stored is not None and stored.diagnostics_json == rejected["diagnostics"]
    mismatch = importer.import_environmental_file(
        path,
        ImportOptions(
            options.layer_id,
            expected_count=3,
        ),
        dry_run=False,
    )
    assert mismatch["status"] == "failed" and mismatch["coverage"] == "partial"
    checks.append("duplicates-missing-identity-invalid-topology-and-count-mismatch-quarantined")

    original_stream = importer.stream_overlay_features
    changing_options = ImportOptions(options.layer_id, scope_id="mutation-test", batch_size=1)

    def changed_stream(*args, **kwargs):
        changed = copy.deepcopy(source)
        changed[0]["features"]["features"][0]["id"] = "changed-during-import"
        path.write_text(json.dumps(changed))
        yield from original_stream(*args, **kwargs)

    try:
        with patch.object(importer, "stream_overlay_features", changed_stream):
            importer.import_environmental_file(path, changing_options, dry_run=False)
    except InputChangedError:
        pass
    else:
        raise AssertionError("Mutated input was accepted")
    path.write_text(json.dumps(source))
    try:
        importer.import_environmental_file(path, changing_options, dry_run=False)
    except InputChangedError as exc:
        assert str(exc) == "input_changed_version_quarantined"
    else:
        raise AssertionError("Mixed chunks were allowed to resume")
    checks.append("changed-input-terminal-quarantine-prevents-mixed-version-resume")

    response = httpx.get(f"{api_url}/api/map/layers", timeout=10)
    assert response.status_code == 200
    body = response.json()
    assert body["layers"] == ready["layers"]
    assert len(body["imports"]) == 1 and body["imports"][0]["status"] == "failed"
    assert len(response.content) <= 50 * 1024 and "private-p03" not in response.text
    checks.append("real-api-progress-bounded-and-prior-ready-catalog-preserved")

    # New producer output takes the streaming bridge, with no network source fetch.
    first_layer = fixture()[0]
    first_layer.update({"id": "new-layer-private-key", "name": "New environmental fixture"})
    first_layer["features"]["features"][0].pop("id")
    bridge = import_environmental_output(
        [first_layer],
        source_health=[
            {
                "source_url": first_layer["source_url"],
                "status": "healthy",
                "metadata": {"reported_count": True, "fetched_count": 2},
            }
        ],
    )
    assert bridge[0]["status"] == "failed" and bridge[0]["expected"] is None
    assert bridge[0]["accepted"] == 1 and bridge[0]["rejected"] == 1
    refreshed = httpx.get(f"{api_url}/api/map/layers", timeout=10).json()
    assert refreshed["layers"][0] == ready["layers"][0]
    new_layer = next(layer for layer in refreshed["layers"] if layer["id"] == first_layer["id"])
    assert new_layer["title"] == first_layer["name"] and new_layer["delivery_status"] == "failed"
    checks.append("new-output-streamed-bridge-adds-human-title-without-changing-ready-layer")

    incoming = _project_legacy_catalog([(metadata(), 2), (first_layer, 2)]).model_dump(mode="json")
    before_refresh = refreshed
    pipeline_result = _write_postgres_source_state(
        run_id="p03-new-output",
        checked_at=datetime.now(UTC).isoformat(),
        source_health=[
            {
                "key": first_layer["id"],
                "source_url": first_layer["source_url"],
                "status": "healthy",
                "error_count": 0,
                "metadata": {"reported_count": True, "fetched_count": 2},
            }
        ],
        raw_records=[],
        staged_records=[],
        published_records=[],
        overlays=[first_layer],
        catalog=incoming,
    )
    assert pipeline_result["environmental_imports"][0]["status"] == "failed"
    durable_health = read_processed_payload("source_health")
    assert durable_health is not None and "environmental_imports" not in durable_health
    after_refresh_response = httpx.get(f"{api_url}/api/map/layers", timeout=10)
    assert after_refresh_response.status_code == 200
    after_refresh = after_refresh_response.json()
    assert after_refresh["imports"] == before_refresh["imports"]
    assert after_refresh["layers"][0] == ready["layers"][0]
    checks.append("canonical-refresh-preserves-imports-hash-and-post-commit-shadow-failure")

    # A later shadow import must expose its own scope and source provenance.
    # The already-ready layer remains pinned to its previous public metadata.
    changed_layer = fixture()[0]
    changed_layer.update({
        "id": first_layer["id"],
        "name": "Revised environmental fixture",
        "category": "floodplain",
        "source_url": "https://example.test/revised-environment",
        "attribution": "Revised synthetic source",
        "caveat": "Revised fixture only",
    })
    changed_path = output / "revised-overlay.json"
    changed_path.write_text(json.dumps([changed_layer]), encoding="utf-8")
    changed_report = importer.import_environmental_file(
        changed_path,
        ImportOptions(first_layer["id"], scope_id="revised-synthetic-scope"),
        dry_run=False,
    )
    assert changed_report["status"] == "validated"
    changed_catalog = httpx.get(f"{api_url}/api/map/layers", timeout=10).json()
    assert changed_catalog["layers"][0] == ready["layers"][0]
    changed_entry = next(
        layer for layer in changed_catalog["layers"] if layer["id"] == first_layer["id"]
    )
    assert changed_entry["delivery_status"] == "processing"
    assert changed_entry["coverage"]["scope_id"] == "revised-synthetic-scope"
    assert changed_entry["title"] == changed_layer["name"]
    assert changed_entry["category"] == changed_layer["category"]
    assert changed_entry["source_name"] == changed_layer["attribution"]
    assert changed_entry["source_url"] == changed_layer["source_url"]
    assert changed_entry["attribution"] == changed_layer["attribution"]
    assert changed_entry["caveat"] == changed_layer["caveat"]
    checks.append("non-ready-reimport-refreshes-scope-and-source-provenance")

    snapshot_reports = verify_snapshot(snapshot) if snapshot else None
    return {
        "checks": checks,
        "fixture_sha256": checksum,
        "dry_run": dry_run,
        "resume": resumed,
        "rejected": rejected,
        "snapshot": snapshot_reports,
        "indexes": [dict(row._mapping) for row in indexes],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("seed-legacy", "verify"), required=True)
    parser.add_argument("--api-url")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--snapshot", type=Path)
    args = parser.parse_args()
    if args.phase == "seed-legacy":
        seed_legacy(args.output)
        return
    result = verify(args.api_url, args.output, args.snapshot)
    (args.output / "results.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"checks": result["checks"]}))


if __name__ == "__main__":
    main()
