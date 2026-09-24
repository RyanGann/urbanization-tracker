from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

from app.ingestion.display_builder import _source_snapshot
from app.ingestion.display_config import BANDS, config_hash, display_version, recipe


def test_display_version_is_configured_and_independent_of_batch_size() -> None:
    data_version = "a" * 64
    assert len(config_hash()) == 64
    assert display_version(data_version, "c" * 64) != display_version("b" * 64, "c" * 64)
    assert display_version(data_version, "c" * 64) != display_version(data_version, "d" * 64)
    assert len(display_version(data_version, "c" * 64)) == 64
    assert [(band.minzoom, band.maxzoom, band.tolerance_m) for band in BANDS] == [
        (8, 10, 100), (11, 12, 40), (13, 14, 10), (15, 16, 2), (17, 18, 0),
    ]
    assert recipe()["transform_order"] == [
        "transform_full_feature", "simplify_preserve_topology_full_feature", "subdivide",
    ]


def test_source_snapshot_uses_stable_source_identities() -> None:
    layer = SimpleNamespace(
        id=41, layer_key="wetlands", data_version="a" * 64,
        source_checksum="b" * 64, import_status="failed", coverage_status="partial",
        import_checkpoint=2, expected_count=3, seen_count=2, accepted_count=2,
        rejected_count=0, duplicate_count=0,
    )
    session = Mock()
    session.execute.return_value = [("source-a", "c" * 64), ("source-b", "d" * 64)]
    first = _source_snapshot(session, layer)
    layer.id = 999  # copied database assigned different local surrogate keys
    assert _source_snapshot(session, layer) == first
    query = str(session.execute.call_args.args[0])
    assert "SELECT source_feature_id, import_fingerprint" in query
    assert "ORDER BY source_feature_id" in query
    layer.accepted_count = 3
    assert _source_snapshot(session, layer) != first
