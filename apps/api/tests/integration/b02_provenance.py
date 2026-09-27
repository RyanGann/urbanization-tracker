"""Synthetic local HTTP → durable observation → real PostGIS proof/SQL fences."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Event
from typing import Any
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from d01_scoped import _scope_file
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.config import get_settings
from app.db import SessionLocal
from app.ingestion import cli
from app.ingestion.artifact_service import ArtifactService
from app.ingestion.environmental_attestation import (
    attest_prepared,
    import_and_validate,
    require_environmental_provenance,
)
from app.ingestion.environmental_proof import (
    ProvenanceError,
    prepare_observation,
    upload_observation,
)
from app.ingestion.scoped_arcgis import (
    SOURCE_CONFIGS,
    CollectionBudget,
    ReviewedScope,
    stage_scoped_source,
)
from app.ingestion.sources.huntsville import FEMA_FLOODPLAIN_1PCT
from app.models import ArtifactReference
from app.transactional_store import CollectionUnitOfWork

SOURCE = FEMA_FLOODPLAIN_1PCT.key
NORMAL_ROLE = "b02_fixture_writer"


class Fixture(BaseHTTPRequestHandler):
    requests = 0
    count = 70

    def log_message(self, *_args: object) -> None:
        pass

    def do_GET(self) -> None:  # noqa: N802
        self.respond()

    def do_POST(self) -> None:  # noqa: N802
        self.respond()

    def respond(self) -> None:
        type(self).requests += 1
        encoded = (
            self.rfile.read(int(self.headers.get("Content-Length", 0))).decode()
            if (self.command == "POST")
            else urlsplit(self.path).query
        )
        params = {key: values[0] for key, values in parse_qs(encoded).items()}
        if urlsplit(self.path).path.endswith("/7"):
            payload: dict[str, Any] = {
                "geometryType": "esriGeometryPolygon",
                "supportedQueryFormats": "geoJSON",
                "extent": {"spatialReference": {"wkid": 102629}},
                "objectIdField": "OBJECTID",
                "fields": [{"name": "OBJECTID", "type": "esriFieldTypeOID"}],
                "editingInfo": {"lastEditDate": 1234},
            }
        elif params.get("returnCountOnly") == "true":
            payload = {"count": type(self).count}
        elif params.get("returnIdsOnly") == "true":
            payload = {"objectIds": list(range(type(self).count))}
        else:
            features = []
            for identity in map(int, params["objectIds"].split(",")):
                ring = [[-86.6, 34.4], [-86.5, 34.4], [-86.5, 34.5], [-86.6, 34.5], [-86.6, 34.4]]
                geometry = {"type": "Polygon", "coordinates": [ring]}
                if identity == 0:
                    geometry = {
                        "type": "MultiPolygon",
                        "coordinates": [[ring], [[[x, y + 0.2] for x, y in ring]]],
                    }
                elif identity == 1:
                    geometry["coordinates"].append(
                        [
                            [-86.58, 34.42],
                            [-86.58, 34.44],
                            [-86.56, 34.44],
                            [-86.56, 34.42],
                            [-86.58, 34.42],
                        ]
                    )
                features.append(
                    {
                        "type": "Feature",
                        "properties": {
                            "OBJECTID": identity,
                            "FLD_ZONE": "AE",
                            "private_fixture": "internal",
                        },
                        "geometry": geometry,
                    }
                )
            payload = {"type": "FeatureCollection", "features": features}
        raw = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def settings_for(root: Path):
    return get_settings().model_copy(
        update={
            "ingestion_data_dir": root,
            "artifact_sink": "local",
            "artifact_local_root": root.parent / "objects",
            "artifact_staging_max_bytes": 128 * 1024 * 1024,
        }
    )


def normal(session) -> None:
    session.execute(text("SET LOCAL statement_timeout = '8s'"))
    session.execute(text("SET LOCAL lock_timeout = '3s'"))
    session.execute(text(f"SET LOCAL ROLE {NORMAL_ROLE}"))


def refusal(statement: str, values: dict[str, Any]) -> str:
    try:
        with SessionLocal.begin() as session:
            normal(session)
            session.execute(text(statement), values)
    except DBAPIError as exc:
        return getattr(exc.orig, "sqlstate", "unknown")
    raise AssertionError("normal-role mutation escaped an integrity fence")


def proof_count() -> int:
    with SessionLocal() as session:
        return session.scalar(text("SELECT count(*) FROM environmental_attestations"))


def update_geometry(layer: int, geometry: bytes) -> None:
    with SessionLocal.begin() as session:
        normal(session)
        session.execute(
            text(
                "UPDATE environmental_features SET geometry=ST_GeomFromEWKB(:geom) "
                "WHERE environmental_layer_id=:layer AND source_feature_id='0'"
            ),
            {"geom": geometry, "layer": layer},
        )


def canonical_hash() -> str:
    with SessionLocal() as session:
        payload = {
            name: CollectionUnitOfWork(session).list_processed(name)
            for name in (
                "development_records",
                "environmental_layers",
                "source_health",
            )
        }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def run_cli(
    settings, run: str, workspace: Path, stage: Path | None = None, scope: Path | None = None
) -> dict[str, Any]:
    args = [
        "ingestion",
        "attest-environmental-scoped",
        "--source",
        SOURCE,
        "--workspace",
        str(workspace),
        "--apply",
    ]
    args.extend(
        ["--staged-dir", str(stage), "--scope-file", str(scope)] if stage else (["--run-id", run])
    )
    output = io.StringIO()
    with patch.object(sys, "argv", args), patch.object(cli, "get_settings", return_value=settings):
        with contextlib.redirect_stdout(output):
            cli.main()
    result = json.loads(output.getvalue())
    assert result["status"] == "attested_shadow"
    return result


def feature_lock_orders(layer: int) -> dict[str, Any]:
    """Noncooperating tuple-first SQL must fail closed against parent-first DML."""
    results = []
    for first in ("parent", "feature"):
        parent_ready, feature_ready = Event(), Event()
        proceed = Event()

        def participant(
            kind: str, parent_ready=parent_ready, feature_ready=feature_ready, proceed=proceed
        ) -> str:
            with SessionLocal() as session:
                try:
                    normal(session)
                    if kind == "parent":
                        session.execute(
                            text("SELECT id FROM environmental_layers WHERE id=:layer FOR UPDATE"),
                            {"layer": layer},
                        )
                        parent_ready.set()
                    else:
                        session.execute(
                            text(
                                "SELECT id FROM environmental_features WHERE "
                                "environmental_layer_id=:layer AND source_feature_id='0' "
                                "FOR UPDATE"
                            ),
                            {"layer": layer},
                        )
                        feature_ready.set()
                    assert proceed.wait(10)
                    # The feature writer does not acquire a cooperative parent lock.
                    session.execute(
                        text(
                            "UPDATE environmental_features SET name=name WHERE "
                            "environmental_layer_id=:layer AND source_feature_id='0'"
                        ),
                        {"layer": layer},
                    )
                    return "rolled_back_success"
                except DBAPIError as exc:
                    return getattr(exc.orig, "sqlstate", "unknown")
                finally:
                    session.rollback()

        with ThreadPoolExecutor(max_workers=2) as workers:
            started = workers.submit(participant, first)
            assert (parent_ready if first == "parent" else feature_ready).wait(10)
            second = workers.submit(participant, "feature" if first == "parent" else "parent")
            assert parent_ready.wait(10) and feature_ready.wait(10)
            proceed.set()
            states = [started.result(12), second.result(12)]
        assert any(state.startswith("40") or state == "55P03" for state in states)
        assert all(
            state == "rolled_back_success" or state.startswith("40") or state == "55P03"
            for state in states
        )
        results.append(states)
    return {"feature_lock_orders": results, "lock_failure_transactions_rolled_back": True}


def preproof_checks(service: ArtifactService, observation, root: Path) -> dict[str, Any]:
    prepared = import_and_validate(service, observation)
    layer = prepared.layer_id
    lock_checks = feature_lock_orders(layer)
    with SessionLocal.begin() as session:
        normal(session)
        extra_feature = session.scalar(
            text(
                "INSERT INTO environmental_features"
                "(environmental_layer_id,geometry,import_managed) "
                "SELECT environmental_layer_id,geometry,false FROM environmental_features "
                "WHERE environmental_layer_id=:layer AND source_feature_id='0' RETURNING id"
            ),
            {"layer": layer},
        )
    try:
        import_and_validate(service, observation)
    except ProvenanceError:
        pass
    else:
        raise AssertionError("unmanaged extra feature was excluded from completeness")
    with SessionLocal.begin() as session:
        normal(session)
        session.execute(
            text("DELETE FROM environmental_features WHERE id=:id"), {"id": extra_feature}
        )
    prepared = import_and_validate(service, observation)
    with SessionLocal.begin() as session:
        normal(session)
        # The small acceptance fixture may otherwise choose a sequential scan.
        session.execute(text("SET LOCAL enable_seqscan = off"))
        plan = session.scalar(
            text(
                "EXPLAIN (FORMAT JSON) SELECT id FROM environmental_features WHERE "
                "environmental_layer_id=:layer AND source_feature_id='0' "
                "AND import_managed IS TRUE"
            ),
            {"layer": layer},
        )
        assert "uq_environmental_managed_feature" in json.dumps(plan)
    # Prior edits cannot become trusted merely by capturing their new revision.
    parent_tampers = {
        "name": "'misleading fixture name'",
        "category": "'other'",
        "source_url": "'https://other.invalid'",
        "license_notes": "'unverified rights'",
        "geom_type": "'Point'",
        "expected_count": "999",
        "seen_count": "999",
        "accepted_count": "999",
        "import_checkpoint": "999",
        "bounds_json": "'[0,0,1,1]'::jsonb",
        "diagnostics_json": "'{\"unexpected\":true}'::jsonb",
        "version": "'forged-version'",
    }
    for column, expression in parent_tampers.items():
        with SessionLocal() as session:
            previous = session.scalar(
                text(f"SELECT {column} FROM environmental_layers WHERE id=:layer"),
                {"layer": layer},
            )
        with SessionLocal.begin() as session:
            normal(session)
            session.execute(
                text(f"UPDATE environmental_layers SET {column}={expression} WHERE id=:layer"),
                {"layer": layer},
            )
        try:
            import_and_validate(service, observation)
        except ProvenanceError:
            pass
        else:
            raise AssertionError(f"preexisting parent {column} edit was accepted")
        with SessionLocal.begin() as session:
            normal(session)
            value = json.dumps(previous) if column.endswith("_json") else previous
            assignment = "CAST(:value AS jsonb)" if column.endswith("_json") else ":value"
            session.execute(
                text(f"UPDATE environmental_layers SET {column}={assignment} WHERE id=:layer"),
                {"value": value, "layer": layer},
            )
    prepared = import_and_validate(service, observation)
    with SessionLocal() as session:
        original = bytes(
            session.scalar(
                text(
                    "SELECT ST_AsEWKB(geometry) FROM environmental_features "
                    "WHERE environmental_layer_id=:layer AND source_feature_id='0'"
                ),
                {"layer": layer},
            )
        )
        changed = bytes(
            session.scalar(
                text(
                    "SELECT ST_AsEWKB(ST_Translate(geometry,0.001,0)) "
                    "FROM environmental_features WHERE environmental_layer_id=:layer "
                    "AND source_feature_id='0'"
                ),
                {"layer": layer},
            )
        )
    # Same count and unchanged stored fingerprint must not mask preexisting edits.
    with SessionLocal() as session:
        attributes = session.scalar(
            text(
                "SELECT attributes_json FROM environmental_features WHERE "
                "environmental_layer_id=:layer AND source_feature_id='0'"
            ),
            {"layer": layer},
        )
    with SessionLocal.begin() as session:
        normal(session)
        session.execute(
            text(
                "UPDATE environmental_features SET attributes_json='{}' WHERE "
                "environmental_layer_id=:layer AND source_feature_id='0'"
            ),
            {"layer": layer},
        )
    try:
        import_and_validate(service, observation)
    except ProvenanceError as exc:
        assert str(exc) == "canonical_feature_changed"
    else:
        raise AssertionError("preexisting attributes edit with unchanged fingerprint was accepted")
    with SessionLocal.begin() as session:
        normal(session)
        session.execute(
            text(
                "UPDATE environmental_features SET attributes_json=CAST(:value AS jsonb) WHERE "
                "environmental_layer_id=:layer AND source_feature_id='0'"
            ),
            {"value": json.dumps(attributes), "layer": layer},
        )
    prepared = import_and_validate(service, observation)
    update_geometry(layer, changed)
    try:
        import_and_validate(service, observation)
    except ProvenanceError as exc:
        assert str(exc) == "canonical_feature_changed"
    else:
        raise AssertionError("preexisting geometry-only edit was accepted")
    try:
        attest_prepared(service, prepared)
    except ProvenanceError as exc:
        assert str(exc) == "canonical_revision_changed"
    else:
        raise AssertionError("stale prepared revision was accepted")
    assert proof_count() == 0
    update_geometry(layer, original)
    prepared = import_and_validate(service, observation)

    # Fail after seal/proof insertion and prove the entire transaction rolled back.
    with patch(
        "app.ingestion.environmental_attestation.EnvironmentalAttestationReference",
        side_effect=RuntimeError("synthetic link failure"),
    ):
        try:
            attest_prepared(service, prepared)
        except RuntimeError:
            pass
        else:
            raise AssertionError("injected link failure did not abort")
    with SessionLocal() as session:
        assert (
            session.scalar(
                text(
                    "SELECT count(*) FROM artifact_run_seals WHERE "
                    "source_key=:source AND run_id=:run"
                ),
                {"source": SOURCE, "run": observation.run_id},
            )
            == 0
        )
    assert proof_count() == 0

    # An extra rawSQL reference committed before final insertion invalidates exact set.
    with SessionLocal() as session:
        blob = session.scalar(
            select(ArtifactReference.blob_id)
            .where(
                ArtifactReference.source_key == SOURCE,
                ArtifactReference.run_id == observation.run_id,
            )
            .limit(1)
        )
    extra = uuid4()
    values = {"id": extra, "source": SOURCE, "run": observation.run_id, "blob": blob}
    insert = """INSERT INTO artifact_references(id,source_key,run_id,artifact_type,logical_key,
                blob_id,required) VALUES(:id,:source,:run,'unexpected','000000',:blob,true)"""
    inserted, release = Event(), Event()

    def early_insert() -> None:
        with SessionLocal.begin() as session:
            normal(session)
            session.execute(text(insert), values)
            inserted.set()
            assert release.wait(10)

    with ThreadPoolExecutor(max_workers=2) as workers:
        writer = workers.submit(early_insert)
        assert inserted.wait(10)
        attempt = workers.submit(attest_prepared, service, prepared)
        release.set()
        writer.result(10)
        try:
            attempt.result(10)
        except Exception:
            pass
        else:
            raise AssertionError("extra-reference race was accepted")
    assert proof_count() == 0
    with SessionLocal.begin() as session:
        normal(session)
        session.execute(text("DELETE FROM artifact_references WHERE id=:id"), {"id": extra})

    # Final fence is held before a competing INSERT, which must refuse after commit.
    from app.ingestion import environmental_attestation as attestation

    original_gate = attestation.require_verified_references
    gated, finish = Event(), Event()

    def paused_gate(*args, **kwargs):
        original_gate(*args, **kwargs)
        gated.set()
        assert finish.wait(10)

    with patch.object(attestation, "require_verified_references", paused_gate):
        with ThreadPoolExecutor(max_workers=2) as workers:
            committing = workers.submit(attest_prepared, service, prepared)
            assert gated.wait(10)
            late = workers.submit(refusal, insert, {**values, "id": uuid4()})
            finish.set()
            proof = committing.result(10)
            assert late.result(10) == "P0001"
    assert proof_count() == 1
    return {
        "layer_id": layer,
        "proof_id": str(proof),
        "geometry_only_edit_refused": True,
        "attributes_edit_with_unchanged_fingerprint_refused": True,
        "stale_revision_refused": True,
        "seal_and_proof_rollback": True,
        "reference_race_orders_refused": True,
        "preexisting_parent_tamper_checks": len(parent_tampers),
        **lock_checks,
        "managed_identity_partial_index_eligible": True,
        "unmanaged_extra_feature_refused": True,
    }


def frozen_checks(service: ArtifactService, result: dict[str, Any]) -> dict[str, Any]:
    layer, proof = result["layer_id"], result["attestation_id"]
    with SessionLocal() as session:
        row = session.scalar(
            select(ArtifactReference)
            .where(
                ArtifactReference.source_key == SOURCE,
                ArtifactReference.run_id == result["run_id"],
            )
            .limit(1)
        )
        assert row is not None
        ref, blob = row.id, row.blob_id
    statements = [
        (
            "UPDATE environmental_features SET geometry=ST_Translate(geometry,0.001,0) "
            "WHERE environmental_layer_id=:layer",
            {"layer": layer},
        ),
        (
            "UPDATE environmental_features SET attributes_json='{}', import_fingerprint=:hash "
            "WHERE environmental_layer_id=:layer",
            {"layer": layer, "hash": "0" * 64},
        ),
        (
            "DELETE FROM environmental_features WHERE environmental_layer_id=:layer",
            {"layer": layer},
        ),
        ("UPDATE environmental_layers SET canonical_revision=0 WHERE id=:layer", {"layer": layer}),
        (
            "UPDATE environmental_layers SET source_url='https://other.invalid' WHERE id=:layer",
            {"layer": layer},
        ),
        ("DELETE FROM environmental_layers WHERE id=:layer", {"layer": layer}),
        (
            "UPDATE artifact_references SET source_url='https://other.invalid' WHERE id=:ref",
            {"ref": ref},
        ),
        ("UPDATE artifact_blobs SET sha256=:hash WHERE id=:blob", {"hash": "f" * 64, "blob": blob}),
        (
            "UPDATE artifact_run_seals SET required_set_sha256=:hash WHERE source_key=:source "
            "AND run_id=:run",
            {"hash": "f" * 64, "source": SOURCE, "run": result["run_id"]},
        ),
        ("DELETE FROM environmental_attestations WHERE id=:proof", {"proof": proof}),
        (
            "DELETE FROM environmental_attestation_references WHERE attestation_id=:proof",
            {"proof": proof},
        ),
        ("TRUNCATE environmental_features", {}),
        ("ALTER TABLE environmental_features DISABLE TRIGGER b02_feature", {}),
    ]
    for statement, values in statements:
        assert refusal(statement, values) in {"P0001", "42501"}
    assert (
        refusal(
            "INSERT INTO environmental_attestations(id,environmental_layer_id,source_key,run_id,"
            "sink_id,canonical_revision,proof_sha256,binding_json) "
            "SELECT gen_random_uuid(),environmental_layer_id,source_key,run_id,sink_id,"
            "canonical_revision,proof_sha256,jsonb_build_object('oversized',repeat('x',1048577)) "
            "FROM environmental_attestations WHERE id=:proof",
            {"proof": proof},
        )
        == "23514"
    )
    with SessionLocal.begin() as session:
        try:
            require_environmental_provenance(
                session,
                layer,
                result["data_version"],
                result["input_sha256"],
                result["proof_sha256"],
                expected_sink_id="f" * 64,
            )
        except ProvenanceError:
            pass
        else:
            raise AssertionError("a different configured provider satisfied the gate")
    # Move an unrelated reference into an attested run and add unrelated proof link.
    path = service.settings.ingestion_data_dir / "unrelated.json"
    path.write_text("{}")
    unrelated = service.upload_file(
        path=path,
        source_key=SOURCE,
        run_id=str(uuid4()),
        artifact_type="b02-page",
        logical_key="999999",
        required=True,
        content_type="application/json",
    )
    assert (
        refusal(
            "UPDATE artifact_references SET run_id=:run WHERE id=:id",
            {"run": result["run_id"], "id": unrelated},
        )
        == "P0001"
    )
    assert (
        refusal(
            "INSERT INTO environmental_attestation_references "
            "(attestation_id,reference_id,role,sequence) VALUES(:proof,:ref,'b02-page',999999)",
            {"proof": proof, "ref": unrelated},
        )
        == "P0001"
    )
    with SessionLocal.begin() as session:
        normal(session)
        session.execute(
            text("UPDATE environmental_layers SET loaded_at=clock_timestamp() WHERE id=:layer"),
            {"layer": layer},
        )
        checked = require_environmental_provenance(
            session,
            layer,
            result["data_version"],
            result["input_sha256"],
            result["proof_sha256"],
            expected_sink_id=service.sink_id,
        )
        assert str(checked.id) == proof
    service.audit(ref)  # Frozen identities must not prevent copy verification transitions.
    return {
        "normal_role_freeze_checks": len(statements) + 2,
        "unbound_operational_time_mutable": True,
        "ordinary_copy_audit_allowed": True,
        "oversized_binding_insert_refused": True,
        "wrong_expected_provider_refused": True,
    }


def stage(result_path: Path) -> None:
    root = result_path.parent / "staging"
    (root / "raw").mkdir(parents=True)
    settings = settings_for(root)
    with SessionLocal.begin() as session:
        session.execute(
            text(f"CREATE ROLE {NORMAL_ROLE} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE")
        )
        session.execute(text(f"GRANT USAGE ON SCHEMA public TO {NORMAL_ROLE}"))
        session.execute(
            text(
                f"GRANT SELECT,INSERT,UPDATE,DELETE,TRUNCATE ON ALL TABLES IN SCHEMA "
                f"public TO {NORMAL_ROLE}"
            )
        )
        session.execute(
            text(f"GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA public TO {NORMAL_ROLE}")
        )
    before = canonical_hash()
    server = ThreadingHTTPServer(("127.0.0.1", 0), Fixture)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    endpoint = f"http://127.0.0.1:{server.server_port}"
    config = replace(FEMA_FLOODPLAIN_1PCT, service_url=endpoint)
    try:
        with patch.dict(SOURCE_CONFIGS, {SOURCE: config}):
            scope_path = _scope_file(root / "raw")
            scope = ReviewedScope.load(scope_path)
            capture = stage_scoped_source(
                config,
                scope,
                root / "raw" / "collection",
                budget=CollectionBudget(max_requests=10, max_attempts=1, min_interval_seconds=0),
            )
            assert capture["coverage"] == "complete" and len(capture["pages"]) == 3
            service = ArtifactService(settings, SessionLocal)
            run = upload_observation(service, SOURCE, scope_path, root / "raw" / "collection")
            observation = prepare_observation(service, SOURCE, run, root / "raw" / "prepared")
            checks = preproof_checks(service, observation, root)
            first = run_cli(
                settings, run, root / "raw" / "cli-one", root / "raw" / "collection", scope_path
            )
            second = run_cli(
                settings, run, root / "raw" / "cli-two", root / "raw" / "collection", scope_path
            )
            assert first == second and proof_count() == 1
            checks.update(frozen_checks(service, first))
            assert canonical_hash() == before
            # Checksum-authorized removal of every source/body and generated input.
            for ref in observation.references:
                path = (
                    scope_path
                    if ref.role == "b02-scope"
                    else (
                        root / "raw" / "collection" / "report.json"
                        if ref.role == "b02-report"
                        else root
                        / "raw"
                        / "collection"
                        / (
                            capture["control_artifacts"]
                            if ref.role == "b02-control"
                            else capture["pages"]
                        )[ref.sequence]["path"]
                    )
                )
                service.cleanup_verified(ref.id, path)
            with SessionLocal() as session:
                refs = session.scalars(
                    select(ArtifactReference).where(
                        ArtifactReference.source_key == SOURCE,
                        ArtifactReference.run_id == run,
                    )
                ).all()
            for workspace in ("prepared", "cli-one", "cli-two"):
                for ref in refs:
                    path = (
                        root
                        / "raw"
                        / workspace
                        / (
                            "scope.json"
                            if ref.artifact_type == "b02-scope"
                            else "report.json"
                            if ref.artifact_type == "b02-report"
                            else "canonical.json"
                            if ref.artifact_type == "b02-input"
                            else f"control-{int(ref.logical_key)}.json"
                            if ref.artifact_type == "b02-control"
                            else f"page-{int(ref.logical_key)}.json"
                        )
                    )
                    if path.exists():
                        service.cleanup_verified(ref.id, path)
            assert not any(path.is_file() for path in (root / "raw").rglob("*"))
            recovered = run_cli(settings, run, root / "raw" / "durable-only")
            assert recovered == first
            Fixture.count = 0
            (root / "raw" / "empty-scope").mkdir()
            empty_scope = _scope_file(root / "raw" / "empty-scope")
            empty_capture = stage_scoped_source(
                config,
                ReviewedScope.load(empty_scope),
                root / "raw" / "empty-collection",
                budget=CollectionBudget(max_requests=6, max_attempts=1, min_interval_seconds=0),
            )
            assert empty_capture["coverage"] == "complete" and empty_capture["pages"] == []
            empty = run_cli(
                settings,
                "",
                root / "raw" / "empty-one",
                root / "raw" / "empty-collection",
                empty_scope,
            )
            empty_replay = run_cli(settings, empty["run_id"], root / "raw" / "empty-two")
            assert empty_replay == empty and proof_count() == 2
            with SessionLocal.begin() as session:
                assert (
                    session.scalar(
                        text("SELECT accepted_count FROM environmental_layers WHERE id=:layer"),
                        {"layer": empty["layer_id"]},
                    )
                    == 0
                )
                require_environmental_provenance(
                    session,
                    empty["layer_id"],
                    empty["data_version"],
                    empty["input_sha256"],
                    empty["proof_sha256"],
                    expected_sink_id=service.sink_id,
                )
            output = {
                **first,
                **checks,
                "fixture_http_requests": Fixture.requests,
                "endpoint": endpoint,
                "before_canonical_sha256": before,
                "after_canonical_sha256": canonical_hash(),
                "full_cli_replay_identical": True,
                "durable_only_recovery": True,
                "zero_feature_observation": empty,
            }
            result_path.write_text(json.dumps(output, sort_keys=True) + "\n")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)


def verify(result_path: Path) -> None:
    expected = json.loads(result_path.read_text())
    root = result_path.parent / "staging"
    retained_sink = ArtifactService(settings_for(root), SessionLocal).sink_id
    config = replace(FEMA_FLOODPLAIN_1PCT, service_url=expected["endpoint"])
    with patch.dict(SOURCE_CONFIGS, {SOURCE: config}):
        restored = run_cli(settings_for(root), expected["run_id"], root / "raw" / "copied-restore")
        assert all(restored[key] == expected[key] for key in restored)
        assert canonical_hash() == expected["before_canonical_sha256"]
        with SessionLocal.begin() as session:
            checked = require_environmental_provenance(
                session,
                expected["layer_id"],
                expected["data_version"],
                expected["input_sha256"],
                expected["proof_sha256"],
                expected_sink_id=retained_sink,
            )
            assert str(checked.id) == expected["attestation_id"]
        empty = expected["zero_feature_observation"]
        restored_empty = run_cli(
            settings_for(root), empty["run_id"], root / "raw" / "copied-empty-restore"
        )
        assert restored_empty == empty
        with SessionLocal.begin() as session:
            require_environmental_provenance(
                session,
                empty["layer_id"],
                empty["data_version"],
                empty["input_sha256"],
                empty["proof_sha256"],
                expected_sink_id=retained_sink,
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("stage", "verify"), required=True)
    parser.add_argument("--result", type=Path, required=True)
    args = parser.parse_args()
    (stage if args.phase == "stage" else verify)(args.result)
    print(json.dumps({"phase": args.phase, "status": "passed"}))
