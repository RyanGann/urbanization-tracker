import math

import pytest

from app.ingestion.identity import SourceIdentityError, provisional_public_id, source_record_id
from app.ingestion.normalize import normalize_building_permit
from app.ingestion.source_merge import public_fingerprint


def test_authoritative_source_ids_preserve_zero_and_leading_zeros() -> None:
    assert source_record_id("huntsville_building_permits", {"PermitID": 0}) == "0"
    assert source_record_id("madison_county_subdivisions", {"Subd_ID": "0012"}) == "0012"
    assert provisional_public_id("madison_county_subdivisions", "0012").startswith(
        "madison-county-subdivision-0012-"
    )


@pytest.mark.parametrize("value", [None, "", "   ", False, {}, [], math.inf, "x" * 256])
def test_missing_or_blank_authoritative_id_is_quarantined(value: object) -> None:
    with pytest.raises(SourceIdentityError, match="PermitID"):
        source_record_id("huntsville_building_permits", {"PermitID": value})


def test_normalizer_does_not_fallback_to_mutable_fields_when_source_id_is_missing() -> None:
    with pytest.raises(SourceIdentityError, match="PermitID"):
        normalize_building_permit(
            {
                "properties": {"Subdivision": "Name can change", "TypeOfWork": "Issued"},
                "geometry": {"type": "Point", "coordinates": [-86.6, 34.7]},
            },
            "2026-09-20T00:00:00+00:00",
        )


def test_slug_collisions_keep_distinct_exact_source_anchors() -> None:
    assert provisional_public_id("huntsville_building_permits", "A/B") != provisional_public_id(
        "huntsville_building_permits", "A-B"
    )
    assert provisional_public_id("huntsville_building_permits", "ABC") != provisional_public_id(
        "huntsville_building_permits", "abc"
    )


def test_source_anchor_preserves_whitespace_and_opaque_unicode() -> None:
    assert source_record_id("huntsville_building_permits", {"PermitID": " 007 "}) == " 007 "
    assert source_record_id("huntsville_building_permits", {"PermitID": "§"}) == "§"
    assert provisional_public_id("huntsville_building_permits", "§").startswith(
        "hsv-building-permit-record-"
    )


def test_fingerprint_ignores_checked_time_flag_metadata_and_ring_orientation() -> None:
    record = {
        "public_id": "hsv-test",
        "source_key": "huntsville_new_subdivisions",
        "source_record_id": "001",
        "title": "Stable item",
        "status": "layout",
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[1000000000.0, 0.0], [1000000000.1, 0.0], [1000000000.1, 0.1], [1000000000.0, 0.0]]],
        },
        "source_fields": {"SubdID": "001", "private_note": "do not hash"},
        "proximity_flags": [{"id": "wetlands", "computed_at": "first"}],
        "date_last_checked": "2026-09-20",
    }
    equivalent = {
        **record,
        "date_last_checked": "2026-09-21",
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[1000000000.1, 0.0], [1000000000.0, 0.0], [1000000000.1, 0.1], [1000000000.1, 0.0]]],
        },
        "source_fields": {"SubdID": "001", "private_note": "changed"},
        "proximity_flags": [{"id": "wetlands", "computed_at": "second"}],
    }
    assert public_fingerprint(record) == public_fingerprint(equivalent)
