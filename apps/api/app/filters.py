from __future__ import annotations

from collections.abc import Sequence

from fastapi import HTTPException

SUPPORTED_STATUSES = (
    "layout",
    "preliminary",
    "final",
    "issued_permit",
    "completed",
    "proposed",
)
SUPPORTED_DEVELOPMENT_TYPES = (
    "subdivision",
    "building_permit",
    "public_submission",
)
SUPPORTED_CONFIDENCE_LEVELS = ("low", "medium", "high")
SUPPORTED_FLAGS = (
    "intersects_floodplain",
    "near_protected_area",
    "near_waterway",
    "near_wetland",
)


def parse_filter_values(
    values: Sequence[str] | None,
    *,
    field: str,
    allowed: Sequence[str],
) -> list[str] | None:
    """Normalize a repeated query filter under the absent/all, none/zero contract."""
    if values is None:
        return None

    normalized = list(values)
    if "none" in normalized:
        if any(value != "none" for value in normalized):
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "invalid_filter",
                    "message": f"{field}=none cannot be combined with other values.",
                    "field": field,
                },
            )
        return []

    unknown = sorted(set(normalized).difference(allowed))
    if unknown:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "invalid_filter",
                "message": f"Unsupported {field} filter value(s): {', '.join(unknown)}.",
                "field": field,
            },
        )
    return normalized


def parse_record_filters(
    *,
    status: Sequence[str] | None = None,
    development_type: Sequence[str] | None = None,
    confidence: Sequence[str] | None = None,
    flag: Sequence[str] | None = None,
) -> dict[str, list[str] | None]:
    return {
        "statuses": parse_filter_values(
            status, field="status", allowed=SUPPORTED_STATUSES
        ),
        "development_types": parse_filter_values(
            development_type,
            field="development_type",
            allowed=SUPPORTED_DEVELOPMENT_TYPES,
        ),
        "confidence_levels": parse_filter_values(
            confidence,
            field="confidence",
            allowed=SUPPORTED_CONFIDENCE_LEVELS,
        ),
        "flag_types": parse_filter_values(flag, field="flag", allowed=SUPPORTED_FLAGS),
    }
