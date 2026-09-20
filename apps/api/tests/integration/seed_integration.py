from __future__ import annotations

import json
import os
from pathlib import Path

from app.processed_store import write_processed_list, write_processed_payload


def main() -> None:
    fixture_path = Path("/integration/fixture.json")
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    record = fixture["development_records"][0]
    record["public_id"] = os.environ["INTEGRATION_FIXTURE_ID"]
    record["title"] = os.environ["INTEGRATION_FIXTURE_TITLE"]
    write_processed_list("development_records", fixture["development_records"])
    write_processed_list("staged_development_records", [])
    write_processed_list("environmental_overlays", fixture["environmental_overlays"])
    write_processed_payload("source_health", fixture["source_health"])


if __name__ == "__main__":
    main()
