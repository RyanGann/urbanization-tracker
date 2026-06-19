from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from app.ingestion.artifacts import (
    ensure_data_dirs,
    iso_now,
    read_json,
    record_artifact,
    write_json,
)
from app.ingestion.connectors.arcgis import ArcGISLayerConfig, ArcGISRestConnector
from app.ingestion.normalize import normalize_development_feature
from app.ingestion.proximity import compute_proximity_flags
from app.ingestion.sources.huntsville import (
    BUILDING_PERMITS,
    DEVELOPMENT_SOURCES,
    ENVIRONMENTAL_CONTEXT_SOURCES,
)
from app.ingestion.sources.madison_county import (
    DEVELOPMENT_SOURCES as MADISON_COUNTY_DEVELOPMENT_SOURCES,
)
from app.processed_store import (
    read_processed_list,
    read_processed_payload,
    write_processed_list,
    write_processed_payload,
)


def ingest_huntsville(
    *,
    data_dir: Path,
    permit_limit: int = 500,
    context_limit: int = 2000,
    connector: ArcGISRestConnector | None = None,
) -> dict[str, Any]:
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

    try:
        for source in DEVELOPMENT_SOURCES:
            source_config = _with_runtime_limits(source, permit_limit=permit_limit)
            source_result = _fetch_source(connector, source_config, data_dir, run_id, checked_at)
            source_health.append(source_result["health"])
            raw_records.extend(source_result["raw_records"])
            for feature in source_result["collection"]["features"]:
                staged, published, validation_errors = normalize_development_feature(
                    feature, source.key, checked_at
                )
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

        staged_records = _dedupe_records(staged_records, key="id")
        published_records = _dedupe_records(published_records, key="public_id")
        compute_proximity_flags(published_records, environmental_collections)
        overlays = _environmental_overlays(environmental_collections)

        health = _write_processed_state(
            data_dir=data_dir,
            run_id=run_id,
            checked_at=checked_at,
            source_health=source_health,
            raw_records=raw_records,
            staged_records=staged_records,
            published_records=published_records,
            overlays=overlays,
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
                staged, published, validation_errors = normalize_development_feature(
                    feature, source.key, checked_at
                )
                if validation_errors:
                    source_result["health"]["error_count"] += len(validation_errors)
                    source_result["health"]["validation_errors"].extend(validation_errors)
                staged_records.append(staged)
                published_records.append(published)

        staged_records = _dedupe_records(staged_records, key="id")
        published_records = _dedupe_records(published_records, key="public_id")

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
    for index, feature in enumerate(collection.get("features", [])):
        properties = feature.get("properties") or {}
        source_record_id = (
            properties.get("SubdID")
            or properties.get("PermitID")
            or properties.get("OBJECTID")
            or properties.get("ObjectId")
            or index
        )
        payload = {"type": "Feature", **feature}
        records.append(
            {
                "data_source_key": config.key,
                "source_record_id": str(source_record_id),
                "payload_json": payload,
                "fetched_at": checked_at,
                "payload_sha256": _sha256(payload),
            }
        )
    return records


def _dedupe_records(records: list[dict[str, Any]], *, key: str) -> list[dict[str, Any]]:
    deduped: dict[str, dict[str, Any]] = {}
    for record in records:
        deduped.setdefault(str(record[key]), record)
    return list(deduped.values())


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
) -> dict[str, Any]:
    processed_dir = data_dir / "processed"
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
