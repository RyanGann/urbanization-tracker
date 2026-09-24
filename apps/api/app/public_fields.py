"""Explicit public scalar attributes allowed from source/reviewer provenance."""

from __future__ import annotations

import math
from typing import Any

# This is intentionally one conservative union for API serialization and C03
# fingerprints.  New fields require review here; raw payloads and nested values
# never become public merely because a connector happens to return them.
PUBLIC_SOURCE_FIELD_NAMES = frozenset(
    {
        # Huntsville subdivisions
        "SubdID", "Subdivision", "Phase", "Status", "HousingUnits", "HousingUnitType",
        "CouncilDistrict", "Layout_date", "Prelim_date", "Final_date", "AsBuilt_date",
        "SubdStatus",
        # Huntsville permits
        "PermitID", "Permit_Issue_DateTime", "OccupancyType", "OccupancySubtype",
        "TypeOfWork", "NumberOfUnits", "ShowDetails",
        # Madison County subdivisions (the last two aliases support current and
        # source-schema variants without allowing unbounded arbitrary fields).
        "Subd_ID", "Subd_Name", "Subd_Type", "OBJECTID", "Parcels", "Lots", "Book",
        "Page", "PlatBook", "PlatPage", "DocNum", "YearFiled", "DateFiled",
        # Agenda/reviewer provenance
        "source_document", "source_document_id", "source_document_title", "id", "title",
        "document_date", "meeting_label",
        "parse_confidence", "lot_count", "unit_count", "location",
        # Public submission receipt provenance
        "submission_id", "source_url", "review_required",
    }
)


def public_source_fields(fields: dict[str, Any]) -> dict[str, str | int | float | bool | None]:
    """Return reviewed primitive values only; reject nested/raw data completely."""
    output: dict[str, str | int | float | bool | None] = {}
    for key, value in fields.items():
        if key not in PUBLIC_SOURCE_FIELD_NAMES or not _is_public_scalar(value):
            continue
        output[key] = value
    return output


def _is_public_scalar(value: Any) -> bool:
    return (
        value is None
        or isinstance(value, str | int | bool)
        or (isinstance(value, float) and math.isfinite(value))
    )
