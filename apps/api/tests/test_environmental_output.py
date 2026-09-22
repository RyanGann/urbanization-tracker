from __future__ import annotations

import json

import pytest

from app.ingestion import environmental_output as bridge


@pytest.mark.parametrize("reported", [True, False, -1, 1.5, "2", None])
def test_reported_count_requires_nonnegative_integer(reported) -> None:
    coverage, expected = bridge._coverage_and_expected(
        {"status": "healthy", "metadata": {"reported_count": reported, "fetched_count": 0}}
    )
    assert coverage == "unknown" and expected is None


def test_source_coverage_remains_conservative() -> None:
    assert bridge._coverage_and_expected(
        {"status": "healthy", "metadata": {"reported_count": 2, "fetched_count": 2}}
    ) == ("unknown", 2)
    assert bridge._coverage_and_expected(
        {"status": "healthy", "metadata": {"reported_count": 3, "fetched_count": 2}}
    ) == ("partial", 3)
    assert bridge._coverage_and_expected(
        {"status": "failing", "metadata": {"reported_count": 0, "fetched_count": 0}}
    ) == ("failed", 0)
    assert bridge._coverage_and_expected({"coverage": "complete"}) == ("unknown", None)


def test_bridge_cleans_staging_and_sanitizes_failure_without_mutating_source(monkeypatch) -> None:
    overlay = {"id": "synthetic", "source_url": "https://example.test/source"}
    paths = []

    def failed_import(path, options, *, dry_run):
        paths.append(path)
        assert json.loads(path.read_text()) == [overlay]
        assert not dry_run and options.scope_version == "legacy-capped-v1"
        raise RuntimeError("private source data must not escape")

    monkeypatch.setattr(bridge, "import_environmental_file", failed_import)
    reports = bridge.import_environmental_output([overlay], source_health=[])
    assert reports == [
        {"layer_id": "synthetic", "status": "failed", "code": "environmental_import_failed"}
    ]
    assert not paths[0].exists()
    assert overlay == {"id": "synthetic", "source_url": "https://example.test/source"}
