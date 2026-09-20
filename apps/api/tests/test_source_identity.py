import pytest

from app.ingestion.identity import SourceIdentityError, provisional_public_id, source_record_id
from app.ingestion.normalize import normalize_building_permit


def test_authoritative_source_ids_preserve_zero_and_leading_zeros() -> None:
    assert source_record_id("huntsville_building_permits", {"PermitID": 0}) == "0"
    assert source_record_id("madison_county_subdivisions", {"Subd_ID": "0012"}) == "0012"
    assert provisional_public_id("madison_county_subdivisions", "0012") == (
        "madison-county-subdivision-0012"
    )


@pytest.mark.parametrize("value", [None, "", "   ", False])
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
