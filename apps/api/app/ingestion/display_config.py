"""Versioned, deterministic display-geometry recipe; not a source-coverage claim."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

ALGORITHM_VERSION = "p04a-transform-simplify-subdivide-validate-v3"
MAX_VERTICES = 256
MAX_INPUT_BYTES = 32 * 1024 * 1024
MAX_INPUT_VERTICES = 1_000_000
MAX_PART_BYTES = 64 * 1024 * 1024
MAX_PARTS_PER_FEATURE = 8192
MAX_WEB_MERCATOR_LAT = 85.05112878


@dataclass(frozen=True)
class DisplayBand:
    key: str
    minzoom: int
    maxzoom: int
    tolerance_m: int


BANDS = (
    DisplayBand("z08_10", 8, 10, 100),
    DisplayBand("z11_12", 11, 12, 40),
    DisplayBand("z13_14", 13, 14, 10),
    DisplayBand("z15_16", 15, 16, 2),
    DisplayBand("z17_18", 17, 18, 0),
)


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def recipe(backend_version: str) -> dict[str, Any]:
    if not backend_version:
        raise ValueError("PostGIS execution version is required")
    return {
        "algorithm": ALGORITHM_VERSION,
        "postgis_execution_version": backend_version,
        "source_srid": 4326,
        "display_srid": 3857,
        "geometry_family": "polygon_or_multipolygon_only",
        "transform_order": [
            "transform_full_feature", "simplify_preserve_topology_full_feature", "subdivide",
        ],
        "max_vertices": MAX_VERTICES,
        "bounds": {
            "max_input_bytes": MAX_INPUT_BYTES,
            "max_input_vertices": MAX_INPUT_VERTICES,
            "max_part_bytes": MAX_PART_BYTES,
            "max_parts_per_feature": MAX_PARTS_PER_FEATURE,
        },
        "max_web_mercator_lat": MAX_WEB_MERCATOR_LAT,
        "bands": [
            {"key": band.key, "minzoom": band.minzoom, "maxzoom": band.maxzoom,
             "tolerance_projected_m": band.tolerance_m}
            for band in BANDS
        ],
        "validation": "per_feature_topology_holes_components_finite_extent_v1",
        "band_checksum": "source_id_c_order_output_sha256_v1",
    }


def config_hash(backend_version: str) -> str:
    return sha256(canonical_bytes(recipe(backend_version)))


def display_version(data_version: str, source_snapshot_sha256: str, backend_version: str) -> str:
    for value in (data_version, source_snapshot_sha256):
        if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            raise ValueError("version inputs must be lowercase SHA-256 digests")
    return sha256(canonical_bytes({
        "data_version": data_version,
        "source_snapshot_sha256": source_snapshot_sha256,
        "recipe": recipe(backend_version),
    }))
