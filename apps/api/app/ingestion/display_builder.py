"""Offline, resumable EPSG:3857 display derivatives for P03 polygons.

This module does not publish a catalog version, activate a layer, or change
canonical geometry. P04b and the provenance bridge own those decisions.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.ingestion.display_config import (
    BANDS,
    MAX_VERTICES,
    MAX_WEB_MERCATOR_LAT,
    DisplayBand,
    canonical_bytes,
    config_hash,
    display_version,
    recipe,
    sha256,
)
from app.ingestion.environmental_import import import_session
from app.models import (
    EnvironmentalDisplayBand,
    EnvironmentalDisplayBuild,
    EnvironmentalDisplayFeatureResult,
    EnvironmentalLayer,
)

MAX_INPUT_BYTES = 32 * 1024 * 1024
MAX_PART_BYTES = 64 * 1024 * 1024
MAX_PARTS_PER_FEATURE = 8192
MAX_DIAGNOSTIC_SAMPLES = 25
EMPTY_SHA = "0" * 64


class DisplayBuildError(RuntimeError):
    """A build cannot be trusted as a complete derivative."""


def _bytes(value: Any) -> bytes:
    return bytes(value) if not isinstance(value, bytes) else value


def _next_checksum(prior: str | None, output_sha: str) -> str:
    return sha256(((prior or "") + output_sha).encode())


def _report(
    build: EnvironmentalDisplayBuild, bands: list[EnvironmentalDisplayBand],
    layer: EnvironmentalLayer,
) -> dict[str, Any]:
    return {
        "layer_key": build.layer_key,
        "data_version": build.data_version,
        "source_checksum": build.source_checksum,
        "source_snapshot_sha256": build.source_snapshot_sha256,
        "display_version": build.display_version,
        "config_sha256": build.config_sha256,
        "status": build.status,
        "display_status": build.status,
        "import_status": layer.import_status,
        "coverage_status": layer.coverage_status,
        "source_counts": {
            "expected": layer.expected_count, "seen": layer.seen_count,
            "accepted": layer.accepted_count, "rejected": layer.rejected_count,
        },
        "bands": [
            {
                "key": band.band_key,
                "status": band.status,
                "checkpoint_feature_id": band.checkpoint_feature_id,
                "processed": band.processed_count,
                "parts": band.part_count,
                "collapsed": band.collapsed_count,
                "invalid": band.invalid_count,
                "parts_sha256": band.parts_sha256,
                "diagnostics": band.diagnostics_json,
            }
            for band in bands
        ],
        "publicly_active": False,
    }


def _canonical_layer(session: Session, layer_key: str, version: str) -> EnvironmentalLayer:
    layer = session.scalar(select(EnvironmentalLayer).where(
        EnvironmentalLayer.layer_key == layer_key,
        EnvironmentalLayer.data_version == version,
    ))
    if layer is None or not layer.data_version or not layer.source_checksum:
        raise DisplayBuildError("versioned_import_required")
    if layer.geom_type != "polygon":
        raise DisplayBuildError("unsupported_geometry_family")
    if layer.import_status == "loading" or layer.import_status not in {"validated", "failed"}:
        raise DisplayBuildError("import_not_traversed")
    if not layer.importer_format or not layer.scope_json:
        raise DisplayBuildError("import_provenance_missing")
    return layer


def _feature_count(session: Session, layer_id: int) -> int:
    return int(session.scalar(text("""
        SELECT count(*) FROM environmental_features
        WHERE environmental_layer_id = :layer_id AND import_managed IS TRUE
    """), {"layer_id": layer_id}) or 0)


def _source_snapshot(session: Session, layer: EnvironmentalLayer) -> str:
    """Bind a derivative to the exact P03 import state without collecting IDs."""
    digest = hashlib.sha256()
    digest.update(canonical_bytes({
        "layer_key": layer.layer_key, "data_version": layer.data_version,
        "source_checksum": layer.source_checksum,
        "import_status": layer.import_status,
        "coverage_status": layer.coverage_status,
        "import_checkpoint": layer.import_checkpoint,
        "expected_count": layer.expected_count, "seen_count": layer.seen_count,
        "accepted_count": layer.accepted_count, "rejected_count": layer.rejected_count,
        "duplicate_count": layer.duplicate_count,
    }) + b"\n")
    rows = session.execute(text("""
        SELECT source_feature_id, import_fingerprint
        FROM environmental_features
        WHERE environmental_layer_id = :layer_id AND import_managed IS TRUE
        ORDER BY source_feature_id
    """).execution_options(yield_per=128), {"layer_id": layer.id})
    for source_id, fingerprint in rows:
        digest.update(canonical_bytes([source_id, fingerprint]) + b"\n")
    return digest.hexdigest()


def _ensure_build(
    session: Session, layer: EnvironmentalLayer, version: str, snapshot_sha: str
) -> tuple[EnvironmentalDisplayBuild, list[EnvironmentalDisplayBand]]:
    existing = session.scalar(select(EnvironmentalDisplayBuild).where(
        EnvironmentalDisplayBuild.environmental_layer_id == layer.id,
        EnvironmentalDisplayBuild.display_version == version,
    ))
    if existing is None:
        build = EnvironmentalDisplayBuild(
            environmental_layer_id=layer.id,
            layer_key=str(layer.layer_key),
            data_version=str(layer.data_version),
            source_checksum=str(layer.source_checksum),
            source_snapshot_sha256=snapshot_sha,
            display_version=version,
            config_sha256=config_hash(),
            config_json=recipe(),
            status="building",
            summary_json={},
        )
        session.add(build)
        session.flush()
        bands = [
            EnvironmentalDisplayBand(
                build_id=build.id, band_key=band.key, status="building",
                checkpoint_feature_id=0, processed_count=0, part_count=0,
                collapsed_count=0, invalid_count=0, diagnostics_json={"samples": []},
            )
            for band in BANDS
        ]
        session.add_all(bands)
        session.commit()
        return build, bands
    build = existing
    if (
        build.layer_key != layer.layer_key
        or build.data_version != layer.data_version
        or build.source_checksum != layer.source_checksum
        or build.source_snapshot_sha256 != snapshot_sha
        or build.config_sha256 != config_hash()
        or build.config_json != recipe()
    ):
        raise DisplayBuildError("immutable_build_identity_mismatch")
    bands = list(session.scalars(select(EnvironmentalDisplayBand).where(
        EnvironmentalDisplayBand.build_id == build.id
    ).order_by(EnvironmentalDisplayBand.band_key)).all())
    if {item.band_key for item in bands} != {item.key for item in BANDS}:
        raise DisplayBuildError("required_bands_missing")
    return build, bands


def _next_features(
    session: Session, layer_id: int, checkpoint: int, batch_size: int
) -> list[dict[str, Any]]:
    return [dict(row) for row in session.execute(text("""
        SELECT id, source_feature_id, import_fingerprint,
               octet_length(ST_AsEWKB(geometry)) AS input_bytes,
               CASE WHEN octet_length(ST_AsEWKB(geometry)) <= :max_input_bytes
                    THEN ST_AsEWKB(geometry) END AS input_ewkb,
               ST_NPoints(geometry) AS input_vertices,
               ST_SRID(geometry) AS input_srid,
               ST_IsValid(geometry) AS input_valid,
               ST_IsEmpty(geometry) AS input_empty,
               ST_GeometryType(geometry) AS input_type,
               ST_YMin(Box3D(geometry)) AS south,
               ST_YMax(Box3D(geometry)) AS north
        FROM environmental_features
        WHERE environmental_layer_id = :layer_id AND import_managed IS TRUE
          AND id > :checkpoint
        ORDER BY id LIMIT :batch_size
    """), {
        "layer_id": layer_id, "checkpoint": checkpoint, "batch_size": batch_size,
        "max_input_bytes": MAX_INPUT_BYTES,
    }).mappings().all()]


def _source_holes(session: Session, feature_id: int) -> int:
    return int(session.scalar(text("""
        SELECT COALESCE(sum(ST_NumInteriorRings(d.geom)), 0)
        FROM environmental_features f
        CROSS JOIN LATERAL ST_Dump(f.geometry) AS d
        WHERE f.id = :feature_id
    """), {"feature_id": feature_id}) or 0)


def _display_holes(session: Session, ewkb: bytes) -> int:
    return int(session.scalar(text("""
        SELECT COALESCE(sum(ST_NumInteriorRings(d.geom)), 0)
        FROM ST_Dump(ST_GeomFromEWKB(:ewkb)) AS d
    """), {"ewkb": ewkb}) or 0)


def _simplified(
    session: Session, feature_id: int, tolerance: int
) -> dict[str, Any]:
    row = session.execute(text("""
        WITH projected AS (
            SELECT ST_Transform(geometry, 3857) AS geom
            FROM environmental_features WHERE id = :feature_id
        ), simplified AS (
            SELECT CASE WHEN :tolerance = 0 THEN geom
                        ELSE ST_SimplifyPreserveTopology(geom, :tolerance) END AS geom
            FROM projected
        )
        SELECT ST_AsEWKB(geom) AS ewkb, ST_IsValid(geom) AS valid,
               ST_IsEmpty(geom) AS empty, ST_SRID(geom) AS srid,
               ST_GeometryType(geom) AS kind,
               ST_NumGeometries(geom) AS components,
               ST_XMin(Box3D(geom)) AS west, ST_YMin(Box3D(geom)) AS south,
               ST_XMax(Box3D(geom)) AS east, ST_YMax(Box3D(geom)) AS north
        FROM simplified
    """), {"feature_id": feature_id, "tolerance": tolerance}).mappings().one()
    return dict(row)


def _part_rows(session: Session, ewkb: bytes) -> list[dict[str, Any]]:
    rows = session.execute(text("""
        SELECT ST_AsEWKB(part.geom) AS ewkb,
               ST_SRID(part.geom) AS srid,
               ST_GeometryType(part.geom) AS kind,
               ST_IsValid(part.geom) AS valid,
               ST_NPoints(part.geom) AS vertices,
               ST_XMin(Box3D(part.geom)) AS west,
               ST_YMin(Box3D(part.geom)) AS south,
               ST_XMax(Box3D(part.geom)) AS east,
               ST_YMax(Box3D(part.geom)) AS north
        FROM ST_Subdivide(ST_GeomFromEWKB(:ewkb), :max_vertices) AS sub(geom)
        CROSS JOIN LATERAL ST_Dump(sub.geom) AS part
        LIMIT :max_parts_plus_one
    """), {
        "ewkb": ewkb, "max_vertices": MAX_VERTICES,
        "max_parts_plus_one": MAX_PARTS_PER_FEATURE + 1,
    }).mappings().all()
    return [dict(row) for row in rows]


def _parts_equal_simplified(session: Session, ewkb: bytes) -> bool:
    return bool(session.scalar(text("""
        WITH parts AS (
            SELECT sub.geom
            FROM ST_Subdivide(ST_GeomFromEWKB(:ewkb), :max_vertices) AS sub(geom)
        )
        SELECT ST_Equals(ST_UnaryUnion(ST_Collect(geom)), ST_GeomFromEWKB(:ewkb))
        FROM parts
    """), {"ewkb": ewkb, "max_vertices": MAX_VERTICES}))


def _extent_ok(row: dict[str, Any]) -> bool:
    values = (row.get("west"), row.get("south"), row.get("east"), row.get("north"))
    return all(
        isinstance(value, (int, float)) and math.isfinite(value)
        and abs(value) <= 20_037_509
        for value in values
    )


def _failure_result(
    build: EnvironmentalDisplayBuild, band: DisplayBand,
    feature: dict[str, Any], error_code: str,
) -> EnvironmentalDisplayFeatureResult:
    return EnvironmentalDisplayFeatureResult(
        build_id=build.id, environmental_feature_id=feature["id"],
        band_key=band.key, source_feature_id=str(feature["source_feature_id"]),
        input_fingerprint=str(feature["import_fingerprint"] or EMPTY_SHA),
        # Oversized inputs never become display parts. Keep their rejection
        # bounded without transferring an arbitrarily large EWKB to Python.
        input_geometry_sha256=(
            sha256(_bytes(feature["input_ewkb"]))
            if feature["input_ewkb"] is not None else EMPTY_SHA
        ),
        simplified_geometry_sha256=EMPTY_SHA,
        output_sha256=EMPTY_SHA, status="failed", error_code=error_code,
        part_count=0, source_holes=0, display_holes=0,
        source_components=0, display_components=0, collapsed=False,
    )


def _build_feature(
    session: Session, build: EnvironmentalDisplayBuild, band: DisplayBand,
    feature: dict[str, Any],
) -> tuple[EnvironmentalDisplayFeatureResult, list[bytes]]:
    input_ewkb = (
        _bytes(feature["input_ewkb"])
        if feature["input_ewkb"] is not None else b""
    )
    error = None
    if not feature["source_feature_id"] or not feature["import_fingerprint"]:
        error = "source_identity_or_fingerprint_missing"
    elif feature["input_bytes"] > MAX_INPUT_BYTES:
        error = "input_feature_byte_budget_exceeded"
    elif feature["input_vertices"] > 1_000_000:
        error = "input_feature_vertex_budget_exceeded"
    elif feature["input_srid"] != 4326 or not feature["input_valid"] or feature["input_empty"]:
        error = "invalid_canonical_geometry"
    elif feature["input_type"] not in {"ST_Polygon", "ST_MultiPolygon"}:
        error = "unsupported_geometry_family"
    elif (
        feature["south"] is None or feature["north"] is None
        or not -MAX_WEB_MERCATOR_LAT <= feature["south"]
        or not feature["north"] <= MAX_WEB_MERCATOR_LAT
    ):
        error = "projection_out_of_domain"
    if error is not None:
        return _failure_result(build, band, feature, error), []

    # A per-feature savepoint lets projection/topology failures be accounted for
    # without losing the rest of the batch or advancing the checkpoint silently.
    try:
        with session.begin_nested():
            simplified = _simplified(session, feature["id"], band.tolerance_m)
            if (
                simplified["srid"] != 3857
                or simplified["kind"] not in {"ST_Polygon", "ST_MultiPolygon"}
                or not simplified["valid"]
                or not simplified["empty"] and not _extent_ok(simplified)
            ):
                raise DisplayBuildError("invalid_projected_geometry")
            simplified_ewkb = _bytes(simplified["ewkb"])
            source_holes = _source_holes(session, feature["id"])
            display_holes = _display_holes(session, simplified_ewkb)
            source_components = int(session.scalar(text("""
                SELECT ST_NumGeometries(geometry) FROM environmental_features WHERE id = :id
            """), {"id": feature["id"]}) or 0)
            display_components = int(simplified["components"] or 0)
            if not simplified["empty"] and (
                source_holes != display_holes or source_components != display_components
            ):
                raise DisplayBuildError("hole_or_component_loss")
            parts = [] if simplified["empty"] else _part_rows(session, simplified_ewkb)
            if len(parts) > MAX_PARTS_PER_FEATURE:
                raise DisplayBuildError("part_budget_exceeded")
            part_bytes = [_bytes(part["ewkb"]) for part in parts]
            if sum(len(value) for value in part_bytes) > MAX_PART_BYTES:
                raise DisplayBuildError("part_byte_budget_exceeded")
            for part in parts:
                if (
                    part["srid"] != 3857 or part["kind"] != "ST_Polygon"
                    or not part["valid"] or part["vertices"] > MAX_VERTICES
                    or not _extent_ok(part)
                ):
                    raise DisplayBuildError("invalid_subdivided_part")
            if not simplified["empty"] and (
                not parts or not _parts_equal_simplified(session, simplified_ewkb)
            ):
                raise DisplayBuildError("subdivision_topology_mismatch")
    except DisplayBuildError as exc:
        return _failure_result(build, band, feature, str(exc)), []
    except Exception:
        return _failure_result(build, band, feature, "projection_or_postgis_failure"), []

    part_bytes.sort()
    part_shas = [sha256(value) for value in part_bytes]
    simplified_sha = sha256(simplified_ewkb)
    output_sha = sha256(canonical_bytes({
        "simplified": simplified_sha, "parts": part_shas,
    }))
    result = EnvironmentalDisplayFeatureResult(
        build_id=build.id, environmental_feature_id=feature["id"],
        band_key=band.key, source_feature_id=str(feature["source_feature_id"]),
        input_fingerprint=str(feature["import_fingerprint"]),
        input_geometry_sha256=sha256(input_ewkb),
        simplified_geometry_sha256=simplified_sha,
        output_sha256=output_sha,
        status="collapsed" if simplified["empty"] else "built",
        error_code=None,
        part_count=len(part_bytes), source_holes=source_holes,
        display_holes=display_holes, source_components=source_components,
        display_components=display_components, collapsed=bool(simplified["empty"]),
    )
    return result, part_bytes


def _store_feature(
    session: Session, build: EnvironmentalDisplayBuild, band: EnvironmentalDisplayBand,
    spec: DisplayBand, feature: dict[str, Any],
) -> None:
    result, parts = _build_feature(session, build, spec, feature)
    session.add(result)
    for number, part in enumerate(parts):
        session.execute(text("""
            INSERT INTO environmental_display_parts
                (build_id, environmental_feature_id, band_key, source_feature_id,
                 part_number, geometry_sha256, geometry)
            VALUES (:build_id, :feature_id, :band_key, :source_id,
                    :part_number, :sha256, ST_GeomFromEWKB(:ewkb))
        """), {
            "build_id": build.id, "feature_id": feature["id"],
            "band_key": spec.key, "source_id": str(feature["source_feature_id"]),
            "part_number": number, "sha256": sha256(part), "ewkb": part,
        })
    band.checkpoint_feature_id = feature["id"]
    band.processed_count += 1
    band.part_count += len(parts)
    band.collapsed_count += int(result.collapsed)
    band.invalid_count += int(result.status == "failed")
    band.parts_sha256 = _next_checksum(band.parts_sha256, result.output_sha256)
    if result.error_code:
        diagnostics = dict(band.diagnostics_json or {"samples": []})
        samples = list(diagnostics.get("samples", []))
        if len(samples) < MAX_DIAGNOSTIC_SAMPLES:
            samples.append({
                "source_feature_id": str(feature["source_feature_id"])[:100],
                "code": result.error_code,
            })
        diagnostics["samples"] = samples
        diagnostics[result.error_code] = int(diagnostics.get(result.error_code, 0)) + 1
        band.diagnostics_json = diagnostics


def _validate_checkpoint(
    session: Session, layer: EnvironmentalLayer, build: EnvironmentalDisplayBuild,
    band: EnvironmentalDisplayBand, *, require_complete: bool,
) -> None:
    results = session.scalars(select(EnvironmentalDisplayFeatureResult).where(
        EnvironmentalDisplayFeatureResult.build_id == build.id,
        EnvironmentalDisplayFeatureResult.band_key == band.band_key,
    ).order_by(EnvironmentalDisplayFeatureResult.environmental_feature_id)
     .execution_options(yield_per=128)).yield_per(128)
    chain = None
    result_count = 0
    last_feature_id = 0
    expected_parts = 0
    collapsed_count = 0
    failed_count = 0
    for result in results:
        chain = _next_checksum(chain, result.output_sha256)
        result_count += 1
        last_feature_id = result.environmental_feature_id
        expected_parts += result.part_count
        collapsed_count += int(result.collapsed)
        failed_count += int(result.status == "failed")
    if result_count != band.processed_count:
        raise DisplayBuildError("checkpoint_result_count_mismatch")
    if last_feature_id != band.checkpoint_feature_id:
        raise DisplayBuildError("checkpoint_feature_id_mismatch")
    if chain != band.parts_sha256:
        raise DisplayBuildError("checkpoint_checksum_mismatch")
    if expected_parts != band.part_count:
        raise DisplayBuildError("checkpoint_part_count_mismatch")
    if collapsed_count != band.collapsed_count:
        raise DisplayBuildError("checkpoint_collapse_count_mismatch")
    if failed_count != band.invalid_count:
        raise DisplayBuildError("checkpoint_failure_count_mismatch")
    joined = session.execute(text("""
        SELECT r.environmental_feature_id, r.status, r.part_count,
               r.simplified_geometry_sha256, r.output_sha256,
               p.part_number, p.geometry_sha256,
               ST_AsEWKB(p.geometry) AS ewkb, ST_SRID(p.geometry) AS srid,
               ST_IsValid(p.geometry) AS valid, ST_NPoints(p.geometry) AS vertices
        FROM environmental_display_feature_results r
        LEFT JOIN environmental_display_parts p
          ON p.build_id = r.build_id AND p.band_key = r.band_key
         AND p.environmental_feature_id = r.environmental_feature_id
        WHERE r.build_id = :build_id AND r.band_key = :band_key
        ORDER BY r.environmental_feature_id, p.part_number
    """).execution_options(yield_per=128), {
        "build_id": build.id, "band_key": band.band_key,
    }).mappings()
    total_parts = 0
    current: dict[str, Any] | None = None
    part_shas: list[str] = []

    def finish_feature() -> None:
        if current is None:
            return
        if len(part_shas) != current["part_count"]:
            raise DisplayBuildError("checkpoint_feature_parts_mismatch")
        if current["status"] == "failed":
            if (
                current["simplified_geometry_sha256"] != EMPTY_SHA
                or current["output_sha256"] != EMPTY_SHA
            ):
                raise DisplayBuildError("checkpoint_failed_result_mismatch")
        elif sha256(canonical_bytes({
            "simplified": current["simplified_geometry_sha256"], "parts": part_shas,
        })) != current["output_sha256"]:
            raise DisplayBuildError("checkpoint_output_digest_mismatch")

    for row in joined:
        if (
            current is None
            or row["environmental_feature_id"] != current["environmental_feature_id"]
        ):
            finish_feature()
            current = dict(row)
            part_shas = []
        if row["part_number"] is None:
            continue
        if (
            row["part_number"] != len(part_shas)
            or row["srid"] != 3857 or not row["valid"]
            or row["vertices"] > MAX_VERTICES
            or sha256(_bytes(row["ewkb"])) != row["geometry_sha256"]
        ):
            raise DisplayBuildError("checkpoint_part_digest_or_geometry_mismatch")
        part_shas.append(row["geometry_sha256"])
        total_parts += 1
    finish_feature()
    actual_parts = session.scalar(text("""
        SELECT count(*) FROM environmental_display_parts
        WHERE build_id = :build_id AND band_key = :band_key
    """), {"build_id": build.id, "band_key": band.band_key})
    if total_parts != band.part_count or actual_parts != total_parts:
        raise DisplayBuildError("checkpoint_parts_missing_or_extra")
    originals = session.execute(text("""
        SELECT r.environmental_feature_id, r.input_geometry_sha256,
               r.input_fingerprint, f.import_fingerprint,
               CASE WHEN r.error_code = 'input_feature_byte_budget_exceeded'
                    THEN NULL ELSE ST_AsEWKB(f.geometry) END AS ewkb,
               octet_length(ST_AsEWKB(f.geometry)) AS input_bytes,
               r.error_code
        FROM environmental_display_feature_results r
        JOIN environmental_features f ON f.id = r.environmental_feature_id
        WHERE r.build_id = :build_id AND r.band_key = :band_key
          AND f.environmental_layer_id = :layer_id AND f.import_managed IS TRUE
        ORDER BY r.environmental_feature_id
    """).execution_options(yield_per=128), {
        "build_id": build.id, "band_key": band.band_key, "layer_id": layer.id,
    }).mappings()
    checked = 0
    for row in originals:
        oversized = row["error_code"] == "input_feature_byte_budget_exceeded"
        digest_matches = (
            row["input_bytes"] > MAX_INPUT_BYTES
            and row["input_geometry_sha256"] == EMPTY_SHA
            if oversized else row["ewkb"] is not None
            and sha256(_bytes(row["ewkb"])) == row["input_geometry_sha256"]
        )
        if (
            not digest_matches
            or row["input_fingerprint"] != (row["import_fingerprint"] or EMPTY_SHA)
        ):
            raise DisplayBuildError("canonical_geometry_changed_since_checkpoint")
        checked += 1
    if checked != band.processed_count:
        raise DisplayBuildError("checkpoint_canonical_count_mismatch")
    if require_complete:
        expected = _feature_count(session, layer.id)
        if band.processed_count != expected:
            raise DisplayBuildError("band_feature_count_incomplete")


def build_environmental_display(
    layer_key: str, data_version: str, *, batch_size: int = 8,
    fail_after_batches: int | None = None,
    after_checkpoint: Callable[[int], None] | None = None,
) -> dict[str, Any]:
    """Build shadow derivatives only; no active pointer or public catalog write."""
    if not 1 <= batch_size <= 64:
        raise ValueError("batch_size must be 1..64")
    # Serialize against P03 on this exact canonical version. Its session-level
    # advisory lock survives our per-batch commits and prevents a same-version
    # importer from changing the input while a display build is in flight.
    with import_session(layer_key, data_version) as session:
        layer = _canonical_layer(session, layer_key, data_version)
        if layer.accepted_count != _feature_count(session, layer.id):
            raise DisplayBuildError("canonical_import_count_mismatch")
        snapshot_sha = _source_snapshot(session, layer)
        version = display_version(data_version, snapshot_sha)
        build, stored_bands = _ensure_build(session, layer, version, snapshot_sha)
        by_key = {band.band_key: band for band in stored_bands}
        if build.status == "validated":
            for spec in BANDS:
                band = by_key[spec.key]
                if band.status != "validated":
                    raise DisplayBuildError("validated_build_missing_band")
                _validate_checkpoint(session, layer, build, band, require_complete=True)
            return {**_report(build, stored_bands, layer), "replayed": True}
        completed_batches = 0
        for spec in BANDS:
            band = by_key[spec.key]
            _validate_checkpoint(session, layer, build, band, require_complete=False)
            if band.status == "validated":
                _validate_checkpoint(session, layer, build, band, require_complete=True)
                continue
            band.status = "building"
            session.commit()
            while rows := _next_features(session, layer.id, band.checkpoint_feature_id, batch_size):
                for feature in rows:
                    _store_feature(session, build, band, spec, feature)
                session.commit()  # parts, outcomes and checkpoint commit together
                completed_batches += 1
                if after_checkpoint is not None:
                    after_checkpoint(completed_batches)
                if fail_after_batches == completed_batches:
                    raise RuntimeError("injected_after_display_checkpoint")
            _validate_checkpoint(session, layer, build, band, require_complete=True)
            band.status = "failed" if band.invalid_count else "validated"
            band.finished_at = datetime.now(UTC)
            session.commit()
        build.status = (
            "validated" if all(by_key[spec.key].status == "validated" for spec in BANDS)
            else "failed"
        )
        build.finished_at = datetime.now(UTC)
        build.summary_json = {
            "bands_required": len(BANDS),
            "bands_validated": sum(by_key[spec.key].status == "validated" for spec in BANDS),
            "canonical_feature_count": _feature_count(session, layer.id),
            "total_parts": sum(by_key[spec.key].part_count for spec in BANDS),
            "total_collapsed": sum(by_key[spec.key].collapsed_count for spec in BANDS),
            "total_failed": sum(by_key[spec.key].invalid_count for spec in BANDS),
        }
        session.commit()
        return {**_report(build, stored_bands, layer), "replayed": False}
