from __future__ import annotations

import json
from dataclasses import replace

import pytest

from app.ingestion.environmental_import import ImportOptions, _geometry, _prepare, data_version
from app.ingestion.environmental_stream import (
    InputChangedError,
    inspect_overlay_file,
    stream_overlay_features,
)


def overlay_fixture(features: list[dict], layer_id: str = "synthetic") -> dict:
    return {
        "id": layer_id,
        "name": "Synthetic layer",
        "category": "wetlands",
        "source_url": "https://example.test/environment",
        "attribution": "Synthetic fixture",
        "caveat": "Fixture only",
        "geom_type": "polygon",
        "features": {"type": "FeatureCollection", "features": features},
    }


def point_feature(identity: object = "001") -> dict:
    return {
        "type": "Feature",
        "id": identity,
        "properties": {},
        "geometry": {"type": "Point", "coordinates": [-86.12345678901234, 34.98765432109876]},
    }


def test_streaming_selects_layer_even_when_metadata_follows_geometry(tmp_path) -> None:
    first = overlay_fixture([point_feature("other")], "other")
    wanted = overlay_fixture([point_feature("001"), point_feature(0)])
    wanted = {"features": wanted.pop("features"), **wanted}
    path = tmp_path / "overlays.json"
    path.write_text(json.dumps([first, wanted]))

    checksum, layers = inspect_overlay_file(path)
    features = list(stream_overlay_features(path, index=1, expected_checksum=checksum))

    assert [(layer.metadata["id"], layer.feature_count) for layer in layers] == [
        ("other", 1),
        ("synthetic", 2),
    ]
    assert [feature["id"] for feature in features] == ["001", 0]


def test_changed_file_cannot_finish_the_second_pass(tmp_path) -> None:
    path = tmp_path / "overlays.json"
    path.write_text(json.dumps([overlay_fixture([point_feature()])]))
    checksum, _ = inspect_overlay_file(path)
    path.write_text(json.dumps([overlay_fixture([point_feature("changed")])]))
    with pytest.raises(InputChangedError, match="Input changed"):
        list(stream_overlay_features(path, index=0, expected_checksum=checksum))


@pytest.mark.parametrize("value", [None, True, 1.2, "", " ", [], {}, "x" * 256])
def test_invalid_identity_is_quarantined(value) -> None:
    with pytest.raises(ValueError, match="missing_or_invalid_source_id"):
        _prepare(point_feature(value), ImportOptions("synthetic"))


def test_identity_and_original_coordinates_survive_public_attribute_filtering() -> None:
    feature = point_feature(0)
    feature["properties"] = {"FLD_ZONE": "A", "private_email": "secret@example.test"}
    prepared = _prepare(feature, ImportOptions("synthetic"))
    assert prepared["source_id"] == "0"
    assert json.loads(prepared["geometry"]) == feature["geometry"]
    assert prepared["attributes"] == {"FLD_ZONE": "A"}
    assert "secret" not in json.dumps(prepared)


@pytest.mark.parametrize("coordinates", [[True, 1], [1, float("nan")], [10**1000, 1], [1, 91]])
def test_invalid_coordinates_are_safe_fixed_errors(coordinates) -> None:
    feature = point_feature()
    feature["geometry"]["coordinates"] = coordinates
    with pytest.raises(ValueError, match="invalid_coordinates"):
        _geometry(feature)


def test_source_cannot_inject_diagnostic_text() -> None:
    feature = {**point_feature(), "_import_error": "private-secret-value"}
    with pytest.raises(ValueError) as error:
        _prepare(feature, ImportOptions("synthetic"))
    assert str(error.value) == "invalid_feature"


def test_parser_errors_do_not_include_input_snippets(tmp_path) -> None:
    path = tmp_path / "invalid.json"
    path.write_text('[{"private_email":"secret@example.test",BROKEN}]')
    with pytest.raises(ValueError) as error:
        inspect_overlay_file(path)
    assert str(error.value) == "invalid_overlay_json"


def test_versions_include_scope_and_format_but_not_batch_size() -> None:
    options = ImportOptions("synthetic", scope_id="pilot", scope_version="1")
    original = data_version("a" * 64, options)
    assert data_version("a" * 64, replace(options, batch_size=16)) == original
    assert data_version("a" * 64, replace(options, scope_version="2")) != original
    with pytest.raises(ValueError, match="does not establish complete"):
        replace(options, coverage="complete").scope()


def test_oversized_or_invalid_metadata_is_rejected_before_database_use(tmp_path) -> None:
    payload = overlay_fixture([])
    payload["name"] = "x" * 256
    path = tmp_path / "metadata.json"
    path.write_text(json.dumps([payload]))
    with pytest.raises(ValueError, match="invalid_overlay_metadata"):
        inspect_overlay_file(path)
