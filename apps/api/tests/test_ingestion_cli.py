import json
import sys

import pytest

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


@pytest.mark.parametrize(("coverage", "canary", "exit_code"), [
    ("partial", False, 1),
    ("failed", False, 1),
    ("complete", False, None),
    ("unknown", True, None),
])
def test_scoped_cli_exit_reflects_full_coverage(
    monkeypatch, capsys, coverage: str, canary: bool, exit_code: int | None
) -> None:
    source_key = next(iter(cli.SOURCE_CONFIGS))
    arguments = [
        "urbanization-tracker", "stage-scoped-arcgis", "--scope-file", "reviewed.json",
        "--output-dir", "staging", "--source", source_key,
    ]
    if canary:
        arguments.append("--canary")
    monkeypatch.setattr(sys, "argv", arguments)
    monkeypatch.setattr(cli.ReviewedScope, "load", lambda _path: object())
    monkeypatch.setattr(
        cli, "stage_scoped_source",
        lambda *_args, **_kwargs: {"coverage": coverage},
    )

    if exit_code is None:
        cli.main()
    else:
        with pytest.raises(SystemExit) as stopped:
            cli.main()
        assert stopped.value.code == exit_code
    assert json.loads(capsys.readouterr().out)[0]["coverage"] == coverage
