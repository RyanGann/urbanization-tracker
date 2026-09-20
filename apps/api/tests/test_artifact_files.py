import json

import pytest

from app.artifact_files import write_json_atomically


def test_atomic_json_write_preserves_existing_file_and_cleans_temp_on_fsync_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    destination = tmp_path / "collection.json"
    destination.write_text(json.dumps({"old": True}) + "\n", encoding="utf-8")

    def fail_fsync(_descriptor: int) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("app.artifact_files.os.fsync", fail_fsync)
    with pytest.raises(OSError, match="disk full"):
        write_json_atomically(destination, {"new": True})

    assert json.loads(destination.read_text(encoding="utf-8")) == {"old": True}
    assert list(tmp_path.glob(".collection.json.*.tmp")) == []
