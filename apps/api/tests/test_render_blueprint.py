from pathlib import Path


def test_render_blueprint_defines_ingestion_cron_jobs() -> None:
    render_yaml = _repo_root() / "render.yaml"
    content = render_yaml.read_text(encoding="utf-8")

    assert "urbanization-tracker-huntsville-ingestion" in content
    assert "python -m app.ingestion.cli ingest-huntsville --data-dir /app/data" in content
    assert "urbanization-tracker-agenda-ingestion" in content
    assert (
        "python -m app.ingestion.cli ingest-huntsville-agendas --data-dir /app/data "
        "--document-limit 3"
    ) in content
    assert "urbanization-tracker-madison-county-ingestion" in content
    assert "python -m app.ingestion.cli ingest-madison-county --data-dir /app/data" in content
    assert "PROCESSED_STORE_BACKEND" in content
    assert "PHASE3_STORE_BACKEND" in content


def _repo_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "render.yaml").exists():
            return parent
    raise AssertionError("Could not locate repository root.")
