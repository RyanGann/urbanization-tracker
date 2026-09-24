from __future__ import annotations

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
