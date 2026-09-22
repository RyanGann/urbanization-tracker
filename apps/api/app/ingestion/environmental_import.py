"""Shadow import of immutable original environmental geometry into PostGIS."""

from __future__ import annotations

import hashlib
import json
import math
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from app.config import get_settings
from app.ingestion.environmental_stream import (
    InputChangedError,
    OverlayInput,
    inspect_overlay_file,
    stream_overlay_features,
)
from app.map_layer_catalog import update_import_progress
from app.models import EnvironmentalFeature, EnvironmentalLayer

IMPORT_FORMAT = "environmental-v1"
MAX_BATCH_BYTES = 8 * 1024 * 1024
PUBLIC_ATTRIBUTES = frozenset(
    {
        "FLD_ZONE",
        "ZONE_SUBTY",
        "SFHA_TF",
        "WETLAND_TYPE",
        "WETLAND_CODE",
        "ATTRIBUTE",
        "ACRES",
    }
)


class ImportBusyError(RuntimeError):
    pass


@dataclass(frozen=True)
class ImportOptions:
    layer_id: str
    scope_id: str | None = None
    scope_version: str | None = None
    id_field: str = "@id"
    expected_count: int | None = None
    scope_definition: dict[str, Any] | None = None
    coverage: str = "unknown"
    batch_size: int = 32

    def scope(self) -> dict[str, Any]:
        if not self.layer_id or len(self.layer_id) > 100:
            raise ValueError("Invalid layer ID")
        if self.coverage not in {"unknown", "partial", "failed"}:
            raise ValueError("P03 does not establish complete source coverage")
        if not 1 <= self.batch_size <= 256:
            raise ValueError("Batch size must be between 1 and 256")
        if self.expected_count is not None and self.expected_count < 0:
            raise ValueError("Expected count cannot be negative")
        for value in (self.scope_id, self.scope_version, self.id_field):
            if value is not None and (not value.strip() or len(value) > 255):
                raise ValueError("Invalid scope or identity field")
        definition = self.scope_definition or {}
        if len(json.dumps(definition, allow_nan=False).encode()) > 64 * 1024:
            raise ValueError("Scope definition is too large")
        return {
            "scope_id": self.scope_id,
            "scope_version": self.scope_version,
            "expected_count": self.expected_count,
            "coverage": self.coverage,
            "id_field": self.id_field,
            "definition": definition,
        }


def data_version(checksum: str, options: ImportOptions) -> str:
    return _digest(
        {
            "source_checksum": checksum,
            "layer_id": options.layer_id,
            "scope": options.scope(),
            "import_format": IMPORT_FORMAT,
        }
    )


def _digest(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()


@contextmanager
def import_session(layer_id: str, version: str, *, lock: bool = True) -> Iterator[Session]:
    """Own a nonpooled physical connection for the lifetime of the session lock.

    P03 uses PostgreSQL's one-bigint advisory key space, distinct from C02's
    two-int space. The hash is explicitly namespaced and signed 64-bit.
    """
    settings = get_settings()
    if settings.data_mode != "live" or settings.processed_store_backend != "postgres":
        raise ValueError("Environmental imports require explicit live PostgreSQL storage")
    key = int.from_bytes(
        hashlib.sha256(f"urbanization:p03:environmental:{layer_id}:{version}".encode()).digest()[
            :8
        ],
        "big",
        signed=True,
    )
    engine = create_engine(
        settings.sqlalchemy_database_url,
        poolclass=NullPool,
        connect_args={"connect_timeout": 10},
    )
    try:
        with engine.connect() as connection:
            acquired = False
            try:
                connection.execute(text("SET statement_timeout = '30s'"))
                connection.execute(text("SET lock_timeout = '1500ms'"))
                connection.execute(text("SET client_min_messages = warning"))
                connection.commit()
                if lock:
                    acquired = bool(
                        connection.scalar(
                            text("SELECT pg_try_advisory_lock(:key)"),
                            {"key": key},
                        )
                    )
                    connection.commit()
                    if not acquired:
                        raise ImportBusyError("This layer version is already being imported")
                with Session(bind=connection, expire_on_commit=False) as session:
                    yield session
            finally:
                try:
                    connection.rollback()
                    if acquired:
                        connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})
                        connection.commit()
                except Exception:
                    connection.invalidate()
                    raise
                # NullPool closes the physical connection even when unlock fails.
    finally:
        engine.dispose()


def _identity(feature: dict[str, Any], field: str) -> str | None:
    properties = feature.get("properties")
    value = (
        feature.get("id")
        if field == "@id"
        else (properties.get(field) if isinstance(properties, dict) else None)
    )
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    result = str(value)
    return result if result.strip() and len(result) <= 255 else None


def _geometry(feature: dict[str, Any]) -> dict[str, Any]:
    geometry = feature.get("geometry")
    if not isinstance(geometry, dict):
        raise ValueError("missing_geometry")
    kind, coordinates = geometry.get("type"), geometry.get("coordinates")
    depths = {
        "Point": 0,
        "MultiPoint": 1,
        "LineString": 1,
        "MultiLineString": 2,
        "Polygon": 2,
        "MultiPolygon": 3,
    }
    if not isinstance(kind, str) or kind not in depths:
        raise ValueError("unsupported_geometry")
    if not isinstance(coordinates, list):
        raise ValueError("invalid_coordinates")

    def visit(value: Any, depth: int) -> None:
        if not isinstance(value, list) or not value:
            raise ValueError("invalid_coordinates")
        if depth:
            for child in value:
                visit(child, depth - 1)
        elif (
            len(value) != 2
            or any(
                isinstance(number, bool)
                or not isinstance(number, (int, float))
                or isinstance(number, float)
                and not math.isfinite(number)
                for number in value
            )
            or not -180 <= value[0] <= 180
            or not -90 <= value[1] <= 90
        ):
            raise ValueError("invalid_coordinates")

    visit(coordinates, depths[kind])
    polygons = (
        [coordinates] if kind == "Polygon" else (coordinates if kind == "MultiPolygon" else [])
    )
    for polygon in polygons:
        for ring in polygon:
            if len(ring) < 4 or ring[0] != ring[-1]:
                raise ValueError("invalid_ring")
    lines = (
        [coordinates]
        if kind == "LineString"
        else (coordinates if kind == "MultiLineString" else [])
    )
    if any(len(line) < 2 for line in lines):
        raise ValueError("invalid_line")
    return {"type": kind, "coordinates": coordinates}


def _prepare(
    feature: dict[str, Any], options: ImportOptions, *, geom_type: str | None = None
) -> dict[str, Any]:
    if feature.get("_import_error"):
        code = feature["_import_error"]
        raise ValueError(
            code if code in ("feature_too_large", "feature_not_object") else "invalid_feature"
        )
    if feature.get("type") != "Feature":
        raise ValueError("invalid_feature")
    identity = _identity(feature, options.id_field)
    if identity is None:
        raise ValueError("missing_or_invalid_source_id")
    geometry = _geometry(feature)
    families = {
        "polygon": {"Polygon", "MultiPolygon"},
        "line": {"LineString", "MultiLineString"},
        "point": {"Point", "MultiPoint"},
    }
    if geom_type is not None and geometry["type"] not in families.get(geom_type, set()):
        raise ValueError("geometry_family_mismatch")
    properties = feature.get("properties")
    attributes = {
        key: value
        for key, value in (properties.items() if isinstance(properties, dict) else [])
        if key in PUBLIC_ATTRIBUTES
        and (
            value is None
            or isinstance(value, (bool, int))
            or isinstance(value, float)
            and math.isfinite(value)
            or isinstance(value, str)
            and len(value) <= 512
        )
    }
    return {
        "source_id": identity,
        "geometry": json.dumps(geometry, allow_nan=False),
        "attributes": attributes,
        "fingerprint": _digest([geometry, attributes]),
    }


def _reject(report: dict[str, Any], reason: str, source_id: str | None = None) -> None:
    report["rejected"] += 1
    reasons = report["diagnostics"]["reasons"]
    reasons[reason] = reasons.get(reason, 0) + 1
    if len(report["diagnostics"]["samples"]) < 25:
        report["diagnostics"]["samples"].append({"source_id": source_id, "reason": reason})


def _new_layer(
    overlay: OverlayInput,
    checksum: str,
    version: str,
    options: ImportOptions,
) -> EnvironmentalLayer:
    metadata = overlay.metadata
    return EnvironmentalLayer(
        name=metadata["name"],
        category=metadata["category"],
        source_url=metadata["source_url"],
        license_notes=metadata["attribution"],
        geom_type=metadata["geom_type"],
        layer_key=options.layer_id,
        data_version=version,
        source_checksum=checksum,
        importer_format=IMPORT_FORMAT,
        scope_json=options.scope(),
        import_status="loading",
        coverage_status=options.coverage,
        expected_count=options.expected_count,
        seen_count=0,
        accepted_count=0,
        rejected_count=0,
        duplicate_count=0,
        import_checkpoint=0,
        diagnostics_json={"reasons": {}, "samples": []},
        import_started_at=datetime.now(UTC),
    )


def _report(layer: EnvironmentalLayer) -> dict[str, Any]:
    return {
        "layer_id": layer.layer_key,
        "data_version": layer.data_version,
        "source_checksum": layer.source_checksum,
        "source_url": layer.source_url,
        "attribution": layer.license_notes,
        "scope": layer.scope_json,
        "status": layer.import_status,
        "coverage": layer.coverage_status,
        "expected": layer.expected_count,
        "seen": layer.seen_count or 0,
        "accepted": layer.accepted_count or 0,
        "rejected": layer.rejected_count or 0,
        "duplicates": layer.duplicate_count or 0,
        "checkpoint": layer.import_checkpoint or 0,
        "bounds": layer.bounds_json,
        "diagnostics": layer.diagnostics_json or {"reasons": {}, "samples": []},
    }


def _checkpoint(layer: EnvironmentalLayer, report: dict[str, Any]) -> None:
    layer.seen_count, layer.accepted_count = report["seen"], report["accepted"]
    layer.rejected_count, layer.duplicate_count = report["rejected"], report["duplicates"]
    layer.import_checkpoint = report["checkpoint"]
    layer.diagnostics_json = json.loads(json.dumps(report["diagnostics"]))
    layer.bounds_json = report["bounds"]


def _include_bounds(report: dict[str, Any], values: Any) -> None:
    bounds = [float(value) for value in values]
    current = report["bounds"]
    report["bounds"] = (
        bounds
        if current is None
        else [
            min(current[0], bounds[0]),
            min(current[1], bounds[1]),
            max(current[2], bounds[2]),
            max(current[3], bounds[3]),
        ]
    )


def import_environmental_file(
    path: Path,
    options: ImportOptions,
    *,
    dry_run: bool = True,
    fail_after_batches: int | None = None,
) -> dict[str, Any]:
    """Import a copied legacy overlay array; failure injection is an internal test seam."""
    options.scope()
    checksum, overlays = inspect_overlay_file(path)
    selected = next((item for item in overlays if item.metadata["id"] == options.layer_id), None)
    if selected is None:
        raise ValueError("Requested layer is absent from this input")
    version = data_version(checksum, options)
    with import_session(options.layer_id, version, lock=not dry_run) as session:
        layer = (
            None
            if dry_run
            else session.scalar(
                select(EnvironmentalLayer).where(
                    EnvironmentalLayer.layer_key == options.layer_id,
                    EnvironmentalLayer.data_version == version,
                )
            )
        )
        if layer is not None and layer.import_status == "validated":
            return {**_report(layer), "replayed": True, "dry_run": False}
        if layer is not None and (layer.diagnostics_json or {}).get("failure") == "input_changed":
            raise InputChangedError("input_changed_version_quarantined")
        if layer is None:
            layer = _new_layer(selected, checksum, version, options)
            if not dry_run:
                session.add(layer)
                session.commit()
        elif not dry_run:
            layer.import_status = "loading"
            layer.import_finished_at = None
            session.commit()
        report = _report(layer)
        report.update({"dry_run": dry_run, "original_count": selected.feature_count})
        checkpoint = report["checkpoint"]
        batch_bytes = 0
        batch_count = 0
        completed_batches = 0
        # A disk-backed temporary table enforces dry-run identity without collecting
        # every source ID in Python memory. It disappears with this physical connection.
        if dry_run:
            session.execute(
                text("""
                CREATE TEMP TABLE p03_dry_ids (
                    source_id varchar(255) PRIMARY KEY, fingerprint char(64)
                )
            """)
            )
        try:
            if not dry_run:
                update_import_progress(selected.metadata, report)
            for ordinal, feature in enumerate(
                stream_overlay_features(
                    path,
                    index=selected.index,
                    expected_checksum=checksum,
                ),
                start=1,
            ):
                if ordinal <= checkpoint:
                    continue
                report["seen"] += 1
                report["checkpoint"] = ordinal
                prepared = None
                try:
                    prepared = _prepare(feature, options, geom_type=selected.metadata["geom_type"])
                except ValueError as exc:
                    _reject(report, str(exc), _identity(feature, options.id_field))
                if prepared is not None:
                    batch_bytes += len(prepared["geometry"].encode())
                    _store_feature(session, layer, prepared, report, dry_run=dry_run)
                batch_count += 1
                if batch_count >= options.batch_size or batch_bytes >= MAX_BATCH_BYTES:
                    if not dry_run:
                        _checkpoint(layer, report)
                    session.commit()
                    if not dry_run:
                        update_import_progress(selected.metadata, report)
                    completed_batches += 1
                    if fail_after_batches == completed_batches:
                        raise RuntimeError("injected_after_chunk")
                    batch_bytes, batch_count = 0, 0
            if report["seen"] != selected.feature_count:
                raise InputChangedError("Feature count changed between import passes")
            if options.expected_count is not None and options.expected_count != report["seen"]:
                report["diagnostics"]["reasons"]["expected_count_mismatch"] = 1
            report["status"] = "failed" if report["rejected"] else "validated"
            if options.coverage == "failed" or (
                options.expected_count is not None and options.expected_count != report["seen"]
            ):
                report["status"] = "failed"
            if report["rejected"] or (
                options.expected_count is not None and options.expected_count != report["seen"]
            ):
                if report["coverage"] != "failed":
                    report["coverage"] = "partial"
            if report["status"] == "validated":
                report["diagnostics"].pop("failure", None)
            if not dry_run:
                _checkpoint(layer, report)
                layer.import_status, layer.coverage_status = report["status"], report["coverage"]
                layer.import_finished_at = datetime.now(UTC)
                session.commit()
                update_import_progress(selected.metadata, report)
        except Exception as exc:
            session.rollback()
            if not dry_run:
                session.refresh(layer)
                layer.import_status = "failed"
                diagnostics = dict(layer.diagnostics_json or {})
                diagnostics["failure"] = (
                    "input_changed" if isinstance(exc, InputChangedError) else "import_interrupted"
                )
                layer.diagnostics_json = diagnostics
                session.commit()
                try:
                    update_import_progress(selected.metadata, _report(layer))
                except Exception:
                    # The durable import failure is already committed. A failed
                    # catalog transaction preserves the previous public catalog.
                    pass
            raise
        report["database_bytes"] = session.scalar(
            text("""
            SELECT pg_total_relation_size('environmental_features')
                 + pg_total_relation_size('environmental_layers')
        """)
        )
        report["precision"] = "original EPSG:4326 accepted double precision; no repair or rounding"
        try:
            import resource

            peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            report["process_peak_rss_bytes"] = peak if sys.platform == "darwin" else peak * 1024
        except ImportError:
            report["process_peak_rss_bytes"] = None
        report["memory_scope"] = "process lifetime high-water RSS, not a per-import delta"
        report["legacy_unmanaged_features"] = session.scalar(
            text("SELECT count(*) FROM environmental_features WHERE NOT import_managed")
        )
        report["legacy_duplicate_groups"] = session.scalar(
            text("""
            SELECT count(*) FROM (
                SELECT environmental_layer_id, source_feature_id FROM environmental_features
                WHERE NOT import_managed AND source_feature_id IS NOT NULL
                GROUP BY environmental_layer_id, source_feature_id HAVING count(*) > 1
            ) legacy_duplicates
        """)
        )
        return report


def _store_feature(
    session: Session,
    layer: EnvironmentalLayer,
    feature: dict[str, Any],
    report: dict[str, Any],
    *,
    dry_run: bool,
) -> None:
    identity = feature["source_id"]
    prior = (
        session.scalar(
            text("SELECT fingerprint FROM p03_dry_ids WHERE source_id = :source_id"),
            {"source_id": identity},
        )
        if dry_run
        else session.scalar(
            select(EnvironmentalFeature.import_fingerprint).where(
                EnvironmentalFeature.environmental_layer_id == layer.id,
                EnvironmentalFeature.source_feature_id == identity,
                EnvironmentalFeature.import_managed.is_(True),
            )
        )
    )
    if prior is not None:
        report["duplicates"] += 1
        _reject(
            report,
            "duplicate_source_id" if prior == feature["fingerprint"] else "conflicting_source_id",
            identity,
        )
        return
    spatial = session.execute(
        text("""
        WITH parsed AS (SELECT ST_GeomFromGeoJSON(:geometry) AS geom)
        SELECT ST_IsValid(geom), ST_IsEmpty(geom), ST_XMin(Box3D(geom)),
               ST_YMin(Box3D(geom)), ST_XMax(Box3D(geom)), ST_YMax(Box3D(geom)) FROM parsed
    """),
        {"geometry": feature["geometry"]},
    ).one()
    if not spatial[0] or spatial[1]:
        _reject(report, "invalid_topology", identity)
        return
    if dry_run:
        session.execute(
            text(
                "INSERT INTO p03_dry_ids (source_id, fingerprint) VALUES (:source_id, :fingerprint)"
            ),
            {"source_id": identity, "fingerprint": feature["fingerprint"]},
        )
    else:
        session.add(
            EnvironmentalFeature(
                environmental_layer_id=layer.id,
                source_feature_id=identity,
                attributes_json=feature["attributes"],
                import_managed=True,
                import_fingerprint=feature["fingerprint"],
                geometry=func.ST_GeomFromGeoJSON(feature["geometry"]),
            )
        )
        session.flush()
    report["accepted"] += 1
    _include_bounds(report, spatial[2:])
