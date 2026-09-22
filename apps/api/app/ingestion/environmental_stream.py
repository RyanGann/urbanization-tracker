"""Bounded legacy-overlay traversal; no collection-sized objects are constructed."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO

import ijson
from ijson.common import ObjectBuilder

METADATA_FIELDS = {
    "id",
    "name",
    "category",
    "source_url",
    "attribution",
    "caveat",
    "geom_type",
}
MAX_LAYER_COUNT = 100
MAX_FEATURE_EVENTS = 1_000_000
MAX_FEATURE_BYTES = 16 * 1024 * 1024
MAX_PROPERTY_STRING_BYTES = 8192


class InputChangedError(ValueError):
    pass


class HashingReader:
    def __init__(self, source: BinaryIO) -> None:
        self.source = source
        self.digest = hashlib.sha256()

    def read(self, size: int = -1) -> bytes:
        data = self.source.read(size)
        self.digest.update(data)
        return data


@dataclass(frozen=True)
class OverlayInput:
    index: int
    metadata: dict[str, str]
    feature_count: int


def inspect_overlay_file(path: Path) -> tuple[str, list[OverlayInput]]:
    try:
        return _inspect_overlay_file(path)
    except (ijson.JSONError, OverflowError):
        raise ValueError("invalid_overlay_json") from None


def _inspect_overlay_file(path: Path) -> tuple[str, list[OverlayInput]]:
    overlays: list[OverlayInput] = []
    metadata: dict[str, str] = {}
    count = 0
    feature_array_seen = False
    with path.open("rb") as source:
        reader = HashingReader(source)
        events = iter(ijson.parse(reader, use_float=True))
        if next(events, None) != ("", "start_array", None):
            raise ValueError("Expected a legacy overlay array")
        for prefix, event, value in events:
            if prefix == "item" and event == "start_map":
                if len(overlays) >= MAX_LAYER_COUNT:
                    raise ValueError("Too many layers in the input")
                metadata, count, feature_array_seen = {}, 0, False
            elif prefix == "item" and event == "end_map":
                if not feature_array_seen or not METADATA_FIELDS <= metadata.keys():
                    raise ValueError("Overlay metadata or feature array is missing")
                if (
                    not metadata["id"]
                    or len(metadata["id"]) > 100
                    or (len(metadata["name"]) > 255 or len(metadata["category"]) > 100)
                    or metadata["geom_type"] not in {"polygon", "line", "point"}
                ):
                    raise ValueError("invalid_overlay_metadata")
                if any(item.metadata["id"] == metadata["id"] for item in overlays):
                    raise ValueError("Ambiguous duplicate overlay ID")
                overlays.append(OverlayInput(len(overlays), metadata, count))
            elif prefix == "item":
                if event != "map_key":
                    raise ValueError("Overlay must be an object")
            elif prefix.startswith("item.") and prefix[5:] in METADATA_FIELDS:
                if event != "string" or len(value) > 2048:
                    raise ValueError("Invalid or oversized overlay metadata")
                metadata[prefix[5:]] = value
            elif prefix == "item.features.features" and event == "start_array":
                feature_array_seen = True
            elif prefix == "item.features.features.item" and event not in {
                "end_map",
                "end_array",
                "map_key",
            }:
                count += 1
        return reader.digest.hexdigest(), overlays


def stream_overlay_features(
    path: Path,
    *,
    index: int,
    expected_checksum: str,
) -> Iterator[dict[str, Any]]:
    """Read the full second pass, including after the selected layer, then verify SHA."""
    try:
        yield from _stream_overlay_features(path, index=index, expected_checksum=expected_checksum)
    except (ijson.JSONError, OverflowError):
        raise ValueError("invalid_overlay_json") from None


def _stream_overlay_features(
    path: Path,
    *,
    index: int,
    expected_checksum: str,
) -> Iterator[dict[str, Any]]:
    current_index = -1
    builder: Any = None
    feature_events = 0
    oversized = False
    feature_bytes = 0
    feature_prefix = "item.features.features.item"
    with path.open("rb") as source:
        reader = HashingReader(source)
        for prefix, event, value in ijson.parse(reader, use_float=True):
            if prefix == "item" and event == "start_map":
                current_index += 1
            if current_index != index:
                continue
            if prefix == feature_prefix and event == "start_map":
                builder, feature_events, oversized = ObjectBuilder(), 0, False
                feature_bytes = 0
            if builder is not None and (
                prefix == feature_prefix or prefix.startswith(feature_prefix + ".")
            ):
                feature_events += 1
                value_bytes = len(value.encode()) if isinstance(value, str) else 32
                feature_bytes += value_bytes
                if (
                    feature_events > MAX_FEATURE_EVENTS
                    or feature_bytes > MAX_FEATURE_BYTES
                    or (isinstance(value, str) and value_bytes > MAX_PROPERTY_STRING_BYTES)
                ):
                    oversized = True
                if not oversized:
                    builder.event(event, value)
                if prefix == feature_prefix and event == "end_map":
                    if oversized:
                        yield {"_import_error": "feature_too_large"}
                    else:
                        yield dict(builder.value)
                    builder = None
            elif prefix == feature_prefix and event not in {"end_array", "end_map"}:
                yield {"_import_error": "feature_not_object"}
        if reader.digest.hexdigest() != expected_checksum:
            raise InputChangedError("Input changed between checksum and import passes")
