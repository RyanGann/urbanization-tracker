import json
import sys

from app.config import get_settings
from app.ingestion import cli


def test_hosted_ingestion_can_be_disabled(monkeypatch, capsys) -> None:
    monkeypatch.setenv("HOSTED_INGESTION_ENABLED", "false")
    monkeypatch.setattr(sys, "argv", ["urbanization-tracker", "ingest-huntsville"])
    monkeypatch.setattr(
        cli,
        "ingest_huntsville",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("ingestion should not run")),
    )
    get_settings.cache_clear()

    try:
        cli.main()
    finally:
        get_settings.cache_clear()

    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "disabled"
    assert result["command"] == "ingest-huntsville"
    assert "durable artifact storage" in result["reason"]
