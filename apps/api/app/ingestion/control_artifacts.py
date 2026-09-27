"""Bounded private control bodies; descriptors are not durable coverage proof."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import IO, Any
from uuid import UUID

CONTROL_ROLES = frozenset({
    "initial_metadata", "initial_count", "initial_ids", "final_ids",
    "final_count", "final_metadata",
})
CONTROL_FORMAT = "arcgis-control-body-v1"
MAX_CONTROL_ARTIFACTS = 4
MAX_CONTROL_BYTES = 80 * 1024 * 1024
MAX_CONTROL_DESCRIPTOR_BYTES = 64 * 1024
MAX_PAGE_ARTIFACTS = 1000


class ControlArtifactError(ValueError):
    pass


class ControlBody:
    def __init__(self, body: IO[bytes], count_bytes: Callable[[int], None]) -> None:
        self._body = body
        self._count_bytes = count_bytes

    def write(self, data: bytes, /) -> int:
        self._count_bytes(len(data))
        return self._body.write(data)


class ControlArtifacts:
    def __init__(self, destination: Path, identity: dict[str, str], *,
                 metadata_url: str, query_url: str,
                 expected_queries: dict[str, str]) -> None:
        try:
            self.run_id = str(UUID(identity["run_id"]))
        except (KeyError, ValueError):
            raise ControlArtifactError("control_run_invalid") from None
        self.destination = destination
        self.identity = identity
        self.descriptors: list[dict[str, Any]] = []
        self.received_bytes = 0
        self.metadata_url = metadata_url
        self.query_url = query_url
        self.expected_queries = expected_queries

    @contextmanager
    def capture(self, role: str, event: dict[str, Any]) -> Iterator[ControlBody]:
        if role not in CONTROL_ROLES:
            raise ControlArtifactError("control_role_invalid")
        operation = "metadata" if role.endswith("metadata") else (
            "count" if role.endswith("count") else "ids"
        )
        endpoint = self.metadata_url if operation == "metadata" else self.query_url
        if event["operation"] != operation or event["url"] != endpoint:
            raise ControlArtifactError("control_role_source_mismatch")
        if event["query_sha256"] != self.expected_queries.get(role):
            raise ControlArtifactError("control_role_query_mismatch")
        if any(item["role"] == role for item in self.descriptors):
            raise ControlArtifactError("control_role_repeated")
        if len(self.descriptors) >= MAX_CONTROL_ARTIFACTS:
            raise ControlArtifactError("control_artifact_budget_exceeded")
        sequence = len(self.descriptors)
        name = f"control-{self.run_id}-{sequence:02}-{role}.json"
        target = self.destination / name
        # A collection must not replace proof from an earlier observation.
        if target.exists():
            raise ControlArtifactError("control_artifact_already_exists")
        temporary: Path | None = None
        try:
            with NamedTemporaryFile(mode="w+b", dir=self.destination, delete=False,
                                    prefix=".control-", suffix=".part") as body:
                temporary = Path(body.name)
                yield ControlBody(body.file, self.count_bytes)
                body.flush()
                body.seek(0)
                digest = hashlib.sha256()
                size = 0
                while chunk := body.read(64 * 1024):
                    size += len(chunk)
                    digest.update(chunk)
                descriptor = {
                    **self.identity, "format": CONTROL_FORMAT, "role": role,
                    "sequence": sequence, "path": name, "sha256": digest.hexdigest(),
                    "bytes": size, "url": event["url"], "method": event["method"],
                    "query_sha256": event["query_sha256"], "operation": event["operation"],
                    "status": event["status"],
                    "body_encoding": "http-content-decoded",
                }
                encoded = json.dumps([*self.descriptors, descriptor],
                                     separators=(",", ":")).encode()
                if len(encoded) > MAX_CONTROL_DESCRIPTOR_BYTES:
                    raise ControlArtifactError("control_descriptor_budget_exceeded")
            # Generated names only; link refuses replacement atomically.
            target.hardlink_to(temporary)
            self.descriptors.append(descriptor)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def count_bytes(self, size: int) -> None:
        self.received_bytes += size
        if self.received_bytes > MAX_CONTROL_BYTES:
            raise ControlArtifactError("control_byte_budget_exceeded")
