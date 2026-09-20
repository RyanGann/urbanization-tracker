"""Authoritative source anchors used before any mutable normalization fields."""

from __future__ import annotations

import hashlib
import math
from typing import Any

SOURCE_ID_FIELDS = {
    "huntsville_new_subdivisions": "SubdID",
    "huntsville_building_permits": "PermitID",
    "madison_county_subdivisions": "Subd_ID",
}
PUBLIC_ID_PREFIXES = {
    "huntsville_new_subdivisions": "hsv-subdivision",
    "huntsville_building_permits": "hsv-building-permit",
    "madison_county_subdivisions": "madison-county-subdivision",
}


class SourceIdentityError(ValueError):
    """A source item cannot safely enter a merge without its authoritative anchor."""


def source_record_id(source_key: str, properties: dict[str, Any]) -> str:
    """Return the declared source ID exactly as text, accepting numeric zero and leading zeros."""
    field = SOURCE_ID_FIELDS.get(source_key)
    if field is None:
        raise SourceIdentityError(f"No authoritative source ID field configured for {source_key}")
    value = properties.get(field)
    if value is None or isinstance(value, bool) or isinstance(value, (dict, list, tuple, set)):
        raise SourceIdentityError(f"{source_key} has no usable {field}")
    if isinstance(value, float) and not math.isfinite(value):
        raise SourceIdentityError(f"{source_key} has no usable {field}")
    identifier = str(value).strip()
    if not identifier or len(identifier) > 255:
        raise SourceIdentityError(f"{source_key} has no usable {field}")
    return identifier


def provisional_public_id(source_key: str, source_id: str) -> str:
    """Use only a stable source anchor for new records; registry preserves legacy IDs."""
    prefix = PUBLIC_ID_PREFIXES.get(source_key)
    if prefix is None:
        raise SourceIdentityError(f"No public ID prefix configured for {source_key}")
    readable = _slug(source_id)[:48]
    digest = hashlib.sha256(f"{source_key}\0{source_id}".encode()).hexdigest()[:16]
    return f"{prefix}-{readable}-{digest}"


def _slug(value: str) -> str:
    import re

    text = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    if not text:
        raise SourceIdentityError("source identifier has no URL-safe characters")
    return text
