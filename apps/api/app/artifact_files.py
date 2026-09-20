"""Single-writer artifact helpers.

Each replacement is atomic for one file only. Callers that mutate several files
must not treat this helper as a cross-file transaction.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any


def write_json_atomically(path: Path, payload: Any) -> None:
    """Atomically replace one JSON artifact without ever deleting its prior version."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
