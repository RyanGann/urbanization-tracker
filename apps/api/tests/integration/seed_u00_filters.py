from __future__ import annotations

import json
from pathlib import Path

from app.processed_store import write_processed_list, write_processed_payload


def main() -> None:
    fixture = json.loads(
        Path("/integration/u00_filter_fixture.json").read_text(encoding="utf-8")
    )
    write_processed_list("development_records", fixture["development_records"])
    write_processed_list("staged_development_records", [])
    write_processed_list("environmental_overlays", fixture["environmental_overlays"])
    write_processed_payload("source_health", fixture["source_health"])


if __name__ == "__main__":
    main()
