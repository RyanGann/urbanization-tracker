from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.ingestion.artifacts import (
    ensure_data_dirs,
    iso_now,
    read_json,
    record_artifact,
    write_json,
)
from app.ingestion.connectors.arcgis import ArcGISLayerConfig, ArcGISRestConnector
from app.ingestion.identity import SourceIdentityError, source_record_id
from app.ingestion.normalize import normalize_development_feature
from app.ingestion.proximity import compute_proximity_flags
from app.ingestion.source_merge import SourceBatch, SourceRecord, merge_postgres_batch
from app.ingestion.sources.huntsville import (
    BUILDING_PERMITS,
    DEVELOPMENT_SOURCES,
    ENVIRONMENTAL_CONTEXT_SOURCES,
)
from app.ingestion.sources.madison_county import (
    DEVELOPMENT_SOURCES as MADISON_COUNTY_DEVELOPMENT_SOURCES,
)
from app.map_layer_catalog import build_catalog
from app.processed_store import (
    read_processed_list,
    read_processed_payload,
    write_processed_list,
    write_processed_payload,
)


class ArtifactIdentityIngestionUnsupported(RuntimeError):
    """Artifact mode retains preview reads but cannot safely merge source identities yet."""


def ingest_huntsville(
    *,
    data_dir: Path,
    permit_limit: int = 500,
    context_limit: int = 2000,
    connector: ArcGISRestConnector | None = None,
) -> dict[str, Any]:
    _require_postgres_identity_store()
    ensure_data_dirs(data_dir)
    checked_at = iso_now()
    run_id = checked_at.replace(":", "").replace("+", "Z")
    owned_connector = connector is None
    connector = connector or ArcGISRestConnector()
    source_health: list[dict[str, Any]] = []
    staged_records: list[dict[str, Any]] = []
    published_records: list[dict[str, Any]] = []
    raw_records: list[dict[str, Any]] = []
    environmental_collections: list[tuple[ArcGISLayerConfig, dict[str, Any]]] = []
    environmental_catalog_sources: list[tuple[ArcGISLayerConfig, dict[str, Any]]] = []

    try:
        for source in DEVELOPMENT_SOURCES:
            source_config = _with_runtime_limits(source, permit_limit=permit_limit)
            source_result = _fetch_source(connector, source_config, data_dir, run_id, checked_at)
            source_health.append(source_result["health"])
            raw_records.extend(source_result["raw_records"])
            for feature in source_result["collection"]["features"]:
                try:
                    staged, published, validation_errors = normalize_development_feature(
                        feature, source.key, checked_at
                    )
                except SourceIdentityError as exc:
                    _quarantine_identity(source_result["health"], exc)
                    continue
                if validation_errors:
                    source_result["health"]["error_count"] += len(validation_errors)
                    source_result["health"]["validation_errors"].extend(validation_errors)
                staged_records.append(staged)
                published_records.append(published)

        for source in ENVIRONMENTAL_CONTEXT_SOURCES:
            source_config = _with_context_limit(source, context_limit)
            source_result = _fetch_source(connector, source_config, data_dir, run_id, checked_at)
            source_health.append(source_result["health"])
            environmental_collections.append((source, source_result["collection"]))
            environmental_catalog_sources.append((source, source_result["health"]))

        staged_records, published_records = _quarantine_duplicate_source_records(
            staged_records, published_records, source_health
        )
        compute_proximity_flags(published_records, environmental_collections)
        overlays = _environmental_overlays(environmental_collections)
        catalog = build_catalog(environmental_catalog_sources)

        health = _write_processed_state(
            data_dir=data_dir,
            run_id=run_id,
            checked_at=checked_at,
            source_health=source_health,
            raw_records=raw_records,
            staged_records=staged_records,
            published_records=published_records,
            overlays=overlays,
            catalog=catalog,
        )
        write_json(data_dir / "runs" / f"{run_id}.json", health)
        return health
    finally:
        if owned_connector:
            connector.close()


def ingest_madison_county(
    *,
    data_dir: Path,
    record_limit: int = 500,
    connector: ArcGISRestConnector | None = None,
) -> dict[str, Any]:
    _require_postgres_identity_store()
    ensure_data_dirs(data_dir)
    checked_at = iso_now()
    run_id = checked_at.replace(":", "").replace("+", "Z")
    owned_connector = connector is None
    connector = connector or ArcGISRestConnector()
    source_health: list[dict[str, Any]] = []
    staged_records: list[dict[str, Any]] = []
    published_records: list[dict[str, Any]] = []
    raw_records: list[dict[str, Any]] = []

    try:
        for source in MADISON_COUNTY_DEVELOPMENT_SOURCES:
            source_config = _with_record_limit(source, record_limit)
            source_result = _fetch_source(connector, source_config, data_dir, run_id, checked_at)
            source_health.append(source_result["health"])
            raw_records.extend(source_result["raw_records"])
            for feature in source_result["collection"]["features"]:
                try:
                    staged, published, validation_errors = normalize_development_feature(
                        feature, source.key, checked_at
                    )
                except SourceIdentityError as exc:
                    _quarantine_identity(source_result["health"], exc)
                    continue
                if validation_errors:
                    source_result["health"]["error_count"] += len(validation_errors)
                    source_result["health"]["validation_errors"].extend(validation_errors)
                staged_records.append(staged)
                published_records.append(published)

        staged_records, published_records = _quarantine_duplicate_source_records(
            staged_records, published_records, source_health
        )

        health = _write_processed_state(
            data_dir=data_dir,
            run_id=run_id,
            checked_at=checked_at,
            source_health=source_health,
            raw_records=raw_records,
            staged_records=staged_records,
            published_records=published_records,
        )
        write_json(data_dir / "runs" / f"{run_id}.json", health)
        return health
    finally:
        if owned_connector:
            connector.close()


def _fetch_source(
    connector: ArcGISRestConnector,
    config: ArcGISLayerConfig,
    data_dir: Path,
    run_id: str,
    checked_at: str,
) -> dict[str, Any]:
    health: dict[str, Any] = {
        "key": config.key,
        "name": config.name,
        "source_url": config.layer_url,
        "status": "healthy",
        "checked_at": checked_at,
        "records_seen": 0,
        "records_created": 0,
        "error_count": 0,
        "validation_errors": [],
        "metadata": {},
        "raw_artifact": None,
    }

    try:
        metadata = connector.get_layer_metadata(config)
        count = connector.get_count(config)
        collection = connector.fetch_geojson(config)
        features = collection.get("features", [])
        health["metadata"] = {
            "arcgis_current_version": metadata.get("currentVersion"),
            "source_srid": config.source_srid,
            "canonical_srid": config.canonical_srid,
            "reported_count": count,
            "fetched_count": len(features),
            "geometry_type": metadata.get("geometryType"),
            "supported_query_formats": metadata.get("supportedQueryFormats"),
        }
        health["records_seen"] = len(features)
        health["records_created"] = len(features)
        raw_path = _write_raw_collection(data_dir, config.key, run_id, collection)
        raw_artifact = record_artifact(
            data_dir=data_dir,
            path=raw_path,
            artifact_type="raw_geojson",
            source_key=config.key,
            run_id=run_id,
            source_url=config.layer_url,
            content_type="application/geo+json",
        )
        health["raw_artifact"] = raw_artifact["storage_uri"]
        health["raw_artifact_sha256"] = raw_artifact["sha256"]
        health["raw_artifact_bytes"] = raw_artifact["byte_size"]
        return {
            "health": health,
            "collection": collection,
            "raw_records": _raw_records(config, collection, checked_at),
        }
    except Exception as exc:
        health["status"] = "failing"
        health["error_count"] = 1
        health["validation_errors"].append(str(exc))
        return {
            "health": health,
            "collection": {"type": "FeatureCollection", "features": []},
            "raw_records": [],
        }


def _write_raw_collection(
    data_dir: Path, source_key: str, run_id: str, collection: dict[str, Any]
) -> Path:
    raw_dir = data_dir / "raw" / source_key
    run_path = raw_dir / f"{run_id}.geojson"
    latest_path = raw_dir / "latest.geojson"
    write_json(run_path, collection)
    write_json(latest_path, collection)
    return run_path


def _raw_records(
    config: ArcGISLayerConfig, collection: dict[str, Any], checked_at: str
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for feature in collection.get("features", []):
        properties = feature.get("properties") or {}
        try:
            record_id: str | None = source_record_id(config.key, properties)
        except SourceIdentityError:
            # The raw GeoJSON artifact retains the full rejected feature. It cannot
            # participate in a registry or mutable merge without an anchor.
            record_id = None
        payload = {"type": "Feature", **feature}
        records.append(
            {
                "data_source_key": config.key,
                "source_record_id": record_id,
                "payload_json": payload,
                "fetched_at": checked_at,
                "payload_sha256": _sha256(payload),
            }
        )
    return records


def _quarantine_identity(health: dict[str, Any], error: SourceIdentityError) -> None:
    health["error_count"] += 1
    health["validation_errors"].append(f"identity_quarantined: {error}")


def _dedupe_records(records: list[dict[str, Any]], *, key: str) -> list[dict[str, Any]]:
    deduped: dict[str, dict[str, Any]] = {}
    for record in records:
        deduped.setdefault(str(record[key]), record)
    return list(deduped.values())


def _quarantine_duplicate_source_records(
    staged_records: list[dict[str, Any]],
    published_records: list[dict[str, Any]],
    source_health: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Reject all duplicate anchors before a legacy first-wins dedupe can hide them."""
    source_by_url = {
        str(source.get("source_url")): source
        for source in source_health
        if source.get("source_url") and source.get("key")
    }
    staged_by_provisional_id = {
        str(staged.get("id", "")).removeprefix("stage-"): staged for staged in staged_records
    }
    anchor_counts: dict[tuple[str, str], int] = {}
    for published in published_records:
        staged = staged_by_provisional_id.get(str(published.get("public_id")))
        if staged is None or not staged.get("raw_record_id"):
            continue
        source_key = str(published.get("source_key") or staged.get("source_key") or "")
        if not source_key:
            source = source_by_url.get(str(published.get("source_url")))
            source_key = str(source.get("key")) if source else ""
        if source_key:
            anchor = (source_key, str(staged["raw_record_id"]))
            anchor_counts[anchor] = anchor_counts.get(anchor, 0) + 1
    duplicates = {anchor for anchor, count in anchor_counts.items() if count > 1}
    if not duplicates:
        return staged_records, published_records

    rejected_public_ids: set[str] = set()
    for published in published_records:
        staged = staged_by_provisional_id.get(str(published.get("public_id")))
        if staged is None:
            continue
        source_key = str(published.get("source_key") or staged.get("source_key") or "")
        if not source_key:
            source = source_by_url.get(str(published.get("source_url")))
            source_key = str(source.get("key")) if source else ""
        anchor = (source_key, str(staged.get("raw_record_id")))
        if anchor in duplicates:
            rejected_public_ids.add(str(published.get("public_id")))

    for source_key, source_record_id in sorted(duplicates):
        health = next((item for item in source_health if item.get("key") == source_key), None)
        if health is not None:
            health["error_count"] = int(health.get("error_count", 0)) + 1
            health.setdefault("validation_errors", []).append(
                "identity_quarantined: duplicate authoritative source ID "
                f"{source_record_id!r}; all matching rows were retained only as raw evidence"
            )
    return (
        [
            staged
            for staged in staged_records
            if str(staged.get("id", "")).removeprefix("stage-") not in rejected_public_ids
        ],
        [published for published in published_records if str(published.get("public_id")) not in rejected_public_ids],
    )


def _environmental_overlays(
    environmental_collections: list[tuple[ArcGISLayerConfig, dict[str, Any]]],
) -> list[dict[str, Any]]:
    overlays: list[dict[str, Any]] = []
    for config, collection in environmental_collections:
        overlays.append(
            {
                "id": config.key,
                "name": config.name,
                "category": config.category or "context",
                "source_url": config.layer_url,
                "attribution": config.attribution,
                "caveat": config.caveat or "",
                "geom_type": config.geometry_type,
                "features": collection,
            }
        )
    return overlays


def _with_runtime_limits(config: ArcGISLayerConfig, *, permit_limit: int) -> ArcGISLayerConfig:
    if config.key != BUILDING_PERMITS.key:
        return config
    return ArcGISLayerConfig(**{**config.__dict__, "max_records": permit_limit})


def _with_record_limit(config: ArcGISLayerConfig, record_limit: int) -> ArcGISLayerConfig:
    return ArcGISLayerConfig(**{**config.__dict__, "max_records": record_limit})


def _with_context_limit(config: ArcGISLayerConfig, context_limit: int) -> ArcGISLayerConfig:
    return ArcGISLayerConfig(**{**config.__dict__, "max_records": context_limit})


def _write_processed_state(
    *,
    data_dir: Path,
    run_id: str,
    checked_at: str,
    source_health: list[dict[str, Any]],
    raw_records: list[dict[str, Any]],
    staged_records: list[dict[str, Any]],
    published_records: list[dict[str, Any]],
    overlays: list[dict[str, Any]] | None = None,
    catalog: dict[str, Any] | None = None,
) -> dict[str, Any]:
    processed_dir = data_dir / "processed"
    if get_settings().processed_store_backend == "postgres":
        return _write_postgres_source_state(
            run_id=run_id,
            checked_at=checked_at,
            source_health=source_health,
            raw_records=raw_records,
            staged_records=staged_records,
            published_records=published_records,
            overlays=overlays,
        )
    raw_source_keys = {
        str(record["data_source_key"]) for record in raw_records if record.get("data_source_key")
    }
    source_urls = {
        str(record["source_url"])
        for record in [*staged_records, *published_records]
        if record.get("source_url")
    }

    combined_raw_records = _dedupe_raw_records(
        [
            *(
                record
                for record in _read_processed_list(processed_dir / "raw_records.json")
                if record.get("data_source_key") not in raw_source_keys
            ),
            *raw_records,
        ]
    )
    combined_staged_records = _dedupe_records(
        [
            *(
                record
                for record in _read_processed_collection("staged_development_records", data_dir)
                if record.get("source_url") not in source_urls
            ),
            *staged_records,
        ],
        key="id",
    )
    combined_published_records = _dedupe_records(
        [
            *(
                record
                for record in _read_processed_collection("development_records", data_dir)
                if record.get("source_url") not in source_urls
            ),
            *published_records,
        ],
        key="public_id",
    )

    write_json(processed_dir / "raw_records.json", combined_raw_records)
    write_processed_list(
        "staged_development_records",
        combined_staged_records,
        data_dir=data_dir,
    )
    write_processed_list(
        "development_records",
        combined_published_records,
        data_dir=data_dir,
    )
    if overlays is not None:
        write_processed_list("environmental_overlays", overlays, data_dir=data_dir)
    if catalog is not None:
        write_processed_payload("map_layer_catalog", catalog, data_dir=data_dir)

    merged_sources = _merge_source_health(data_dir, source_health)
    health = {
        "run_id": run_id,
        "checked_at": checked_at,
        "status": _aggregate_status(merged_sources),
        "sources": merged_sources,
        "records": {
            "raw": len(combined_raw_records),
            "staged": len(combined_staged_records),
            "published": len(combined_published_records),
            "proximity_flags": sum(
                len(record.get("proximity_flags", [])) for record in combined_published_records
            ),
        },
    }
    write_processed_payload("source_health", health, data_dir=data_dir)
    return health


def _require_postgres_identity_store() -> None:
    if get_settings().processed_store_backend != "postgres":
        raise ArtifactIdentityIngestionUnsupported(
            "Artifact ingestion cannot preserve C03 source identities; use PostgreSQL or a future "
            "single-writer compatibility import. Existing artifact preview reads remain supported."
        )


def _write_postgres_source_state(
    *,
    run_id: str,
    checked_at: str,
    source_health: list[dict[str, Any]],
    raw_records: list[dict[str, Any]],
    staged_records: list[dict[str, Any]],
    published_records: list[dict[str, Any]],
    overlays: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    from app.db import SessionLocal
    from app.transactional_store import CollectionUnitOfWork

    checked = datetime.fromisoformat(checked_at)
    staged_by_id = {str(record["id"]).removeprefix("stage-"): record for record in staged_records}
    published_by_source: dict[str, list[SourceRecord]] = {}
    source_by_url = {
        str(source.get("source_url")): source
        for source in source_health
        if source.get("source_url") and source.get("key")
    }
    for published in published_records:
        public_id = str(published["public_id"])
        staged = staged_by_id.get(public_id)
        if staged is None:
            continue
        source_key = str(published.get("source_key") or staged.get("source_key") or "")
        if not source_key:
            source = source_by_url.get(str(published.get("source_url")))
            source_key = str(source.get("key")) if source else ""
        if not source_key:
            # A record without source provenance is not safe to attach to an
            # arbitrary batch.  It remains a caller-visible ingestion error.
            raise ValueError(f"Published record {public_id} has no configured source key")
        published_by_source.setdefault(str(source_key), []).append(
            SourceRecord(str(staged["raw_record_id"]), public_id, published, staged)
        )
    with SessionLocal.begin() as session:
        unit = CollectionUnitOfWork(session)
        with unit.canonical_mutation():
            merge_results: dict[str, dict[str, int | bool]] = {}
            for source in source_health:
                source_key = str(source["key"])
                coverage, outcome = _legacy_batch_outcome(source)
                merge_results[source_key] = merge_postgres_batch(
                    session,
                    SourceBatch(
                        run_id=run_id,
                        source_key=source_key,
                        scope_id=str(source.get("source_url", source_key)),
                        scope_version="legacy-capped-v1",
                        coverage=coverage,
                        outcome=outcome,
                        checked_at=checked,
                        records=tuple(published_by_source.get(source_key, [])),
                        quarantined_count=sum(
                            1
                            for error in source.get("validation_errors", [])
                            if "identity_quarantined" in error
                        ),
                    ),
                    unit_of_work=unit,
                )
            existing_health = unit.get_processed("source_health", "latest") or {}
            merged_sources = {
                str(source["key"]): source
                for source in existing_health.get("sources", [])
                if isinstance(source, dict) and source.get("key")
            }
            merged_sources.update(
                {str(source["key"]): source for source in source_health if source.get("key")}
            )
            current_published = unit.list_processed("development_records")
            health = {
                "run_id": run_id,
                "checked_at": checked_at,
                "status": _aggregate_status(list(merged_sources.values())),
                "sources": list(merged_sources.values()),
                "records": {
                    "raw": len(raw_records),
                    "staged": len(unit.list_processed("staged_development_records")),
                    "published": len(current_published),
                    "proximity_flags": sum(
                        len(record.get("proximity_flags", [])) for record in current_published
                    ),
                },
                "batches": merge_results,
            }
            unit.upsert_processed("source_health", "latest", health)
            for raw_record in raw_records:
                source_key = str(raw_record.get("data_source_key") or "unknown")
                payload_digest = str(raw_record.get("payload_sha256") or _sha256(raw_record))
                raw_key = f"{source_key}:{run_id}:{payload_digest}"
                unit.upsert_processed("raw_records", raw_key, {**raw_record, "ingestion_run_id": run_id})
            for overlay in overlays or []:
                overlay_source = source_by_url.get(str(overlay.get("source_url")))
                if overlay_source is not None and overlay_source.get("status") == "failing":
                    continue
                unit.upsert_processed("environmental_overlays", str(overlay["id"]), overlay)
    return health


def _legacy_batch_outcome(source: dict[str, Any]) -> tuple[str | None, str]:
    if source.get("status") == "failing":
        return "failed", "failed"
    metadata = source.get("metadata")
    if isinstance(metadata, dict):
        reported = metadata.get("reported_count")
        fetched = metadata.get("fetched_count")
        if isinstance(reported, int) and isinstance(fetched, int) and reported > fetched:
            return "partial", "success"
    return None, "success"


def _read_processed_list(path: Path) -> list[dict[str, Any]]:
    payload = read_json(path, [])
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def _read_processed_collection(name: str, data_dir: Path) -> list[dict[str, Any]]:
    return read_processed_list(name, data_dir=data_dir) or []


def _dedupe_raw_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[str, dict[str, Any]] = {}
    for record in records:
        key = f"{record.get('data_source_key')}:{record.get('source_record_id')}"
        deduped.setdefault(key, record)
    return list(deduped.values())


def _merge_source_health(
    data_dir: Path,
    source_health: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    existing = read_processed_payload("source_health", data_dir=data_dir, default={})
    merged: dict[str, dict[str, Any]] = {}
    if isinstance(existing, dict) and isinstance(existing.get("sources"), list):
        for source in existing["sources"]:
            if isinstance(source, dict) and source.get("key"):
                merged[str(source["key"])] = source
    for source in source_health:
        if source.get("key"):
            merged[str(source["key"])] = source
    return list(merged.values())


def _aggregate_status(source_health: list[dict[str, Any]]) -> str:
    if any(source["status"] == "failing" for source in source_health):
        return "degraded"
    if any(source["error_count"] for source in source_health):
        return "degraded"
    return "healthy"


def _sha256(payload: dict[str, Any]) -> str:
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def latest_health(data_dir: Path) -> dict[str, Any]:
    payload = read_processed_payload(
        "source_health",
        data_dir=data_dir,
        default={"status": "unknown", "sources": [], "records": {}},
    )
    if not isinstance(payload, dict):
        return {"status": "unknown", "sources": [], "records": {}}
    return payload
