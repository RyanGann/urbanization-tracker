import math

import pytest

from app.ingestion import source_backfill
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
            "coordinates": [
                [[1000000000.0, 0.0], [1000000000.1, 0.0], [1000000000.1, 0.1], [1000000000.0, 0.0]]
            ],
        },
        "source_fields": {"SubdID": "001", "private_note": "do not hash"},
        "address": "10 Main Street",
        "parcel_ids": ["parcel-b", "parcel-a"],
        "proximity_flags": [
            {
                "flag_type": "wetlands",
                "label": "Wetland",
                "relationship": "within",
                "distance_m": 12.0,
                "threshold_m": 25.0,
                "source_name": "USFWS",
                "source_url": "https://example.test/wetlands",
                "caveat": "Screening only",
                "computed_at": "first",
                "private_internal": "ignored",
            }
        ],
        "date_last_checked": "2026-09-20",
    }
    equivalent = {
        **record,
        "date_last_checked": "2026-09-21",
        "geometry": {
            "type": "Polygon",
            "coordinates": [
                [[1000000000.1, 0.0], [1000000000.0, 0.0], [1000000000.1, 0.1], [1000000000.1, 0.0]]
            ],
        },
        "source_fields": {"SubdID": "001", "private_note": "changed"},
        "address": "10 Main Street",
        "parcel_ids": ["parcel-a", "parcel-b"],
        "proximity_flags": [
            {
                "flag_type": "wetlands",
                "label": "Wetland",
                "relationship": "within",
                "distance_m": 12.0,
                "threshold_m": 25.0,
                "source_name": "USFWS",
                "source_url": "https://example.test/wetlands",
                "caveat": "Screening only",
                "computed_at": "second",
            }
        ],
    }
    assert public_fingerprint(record) == public_fingerprint(equivalent)
    assert public_fingerprint(record) != public_fingerprint(
        {**equivalent, "address": "11 Main Street"}
    )
    assert public_fingerprint(record) != public_fingerprint(
        {**equivalent, "parcel_ids": ["parcel-a"]}
    )
    changed_relationship = {
        **equivalent,
        "proximity_flags": [{**equivalent["proximity_flags"][0], "relationship": "intersects"}],
    }
    assert public_fingerprint(record) != public_fingerprint(changed_relationship)


class _EmptyRows:
    def all(self) -> list[object]:
        return []


class _BackfillSession:
    def scalars(self, _query: object) -> _EmptyRows:
        return _EmptyRows()


class _BackfillUnit:
    def __init__(self, records: list[dict[str, object]]) -> None:
        self.records = records

    def list_processed(self, collection: str) -> list[dict[str, object]]:
        assert collection == "development_records"
        return self.records


def _backfill_record(public_id: str, anchor: str, discovery: object) -> dict[str, object]:
    return {
        "public_id": public_id,
        "source_key": "huntsville_new_subdivisions",
        "source_fields": {"SubdID": anchor},
        "date_discovered": discovery,
    }


def test_backfill_uses_each_candidate_discovery_date_and_skips_trailing_manual_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = [
        _backfill_record("first", "001", "2024-01-02"),
        _backfill_record("second", "002", "2025-02-03T04:05:06+00:00"),
        _backfill_record("invalid", "003", "not-a-date"),
        {"public_id": "manual-last", "development_type": "public_submission"},
    ]
    monkeypatch.setattr(
        source_backfill,
        "CollectionUnitOfWork",
        lambda _session: _BackfillUnit(records),
    )

    report = source_backfill.dry_run_source_identity_backfill(_BackfillSession())

    assert report["candidates"] == [
        {
            "source_key": "huntsville_new_subdivisions",
            "source_record_id": "001",
            "public_id": "first",
            "first_discovered_at": "2024-01-02T00:00:00+00:00",
        },
        {
            "source_key": "huntsville_new_subdivisions",
            "source_record_id": "002",
            "public_id": "second",
            "first_discovered_at": "2025-02-03T04:05:06+00:00",
        },
    ]
    assert report["diagnostics"] == [{"code": "invalid_discovery_date", "public_id": "invalid"}]
    assert report["skipped"] == [{"code": "out_of_scope_record", "public_id": "manual-last"}]


def test_backfill_refuses_duplicate_public_id_without_selecting_a_stale_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = [
        _backfill_record("duplicate", "001", "2024-01-02"),
        _backfill_record("duplicate", "002", "2025-02-03"),
        {"public_id": "duplicate", "development_type": "public_submission"},
    ]
    monkeypatch.setattr(
        source_backfill,
        "CollectionUnitOfWork",
        lambda _session: _BackfillUnit(records),
    )

    report = source_backfill.dry_run_source_identity_backfill(_BackfillSession())

    assert report["candidates"] == []
    assert report["diagnostics"] == [
        {"code": "duplicate_public_id", "public_id": "duplicate"},
        {"code": "duplicate_public_id", "public_id": "duplicate"},
    ]
