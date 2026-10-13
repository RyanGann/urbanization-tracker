"""Reconcile durable controls and pages into an exact, bounded P03 input.

Consistency proof depends on the restricted collector/operator capture boundary;
these private observations are neither upstream signatures nor owner clearance.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any
from uuid import UUID

from sqlalchemy import select

from app.ingestion.artifact_service import ArtifactService
from app.ingestion.artifact_sink import CHUNK_BYTES, ArtifactError
from app.ingestion.control_artifacts import CONTROL_FORMAT, MAX_CONTROL_BYTES, MAX_PAGE_ARTIFACTS
from app.ingestion.environmental_import import ImportOptions, _prepare
from app.ingestion.scoped_arcgis import (
    SOURCE_CONFIGS,
    ReviewedScope,
    ScopeError,
    _base_query,
    _canonical,
    _count,
    _digest,
    _feature_id,
    _geometry_ok,
    _ids,
    _oid_field,
    _parse_finite_float,
    _properties_ok,
    _reject_nonfinite_constant,
)
from app.models import ArtifactBlob, ArtifactReference

PROOF_FORMAT = "environmental-provenance-v1"
MAX_TOTAL_BYTES = 1024 * 1024 * 1024
MAX_REPORT_BYTES = 1024 * 1024
MAX_PAGE_BYTES = 32 * 1024 * 1024
MAX_IDS = 100_000
MAX_SECONDS = 600
CONTROL_CAPS = {"metadata": 4 * 1024 * 1024, "count": 64 * 1024, "ids": 8 * 1024 * 1024}


class ProvenanceError(ValueError):
    """Bounded diagnostic; never includes private artifact values."""


@dataclass(frozen=True)
class ProofReference:
    id: UUID
    role: str
    sequence: int
    sha256: str
    byte_size: int
    source_url: str | None

    def binding(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "role": self.role,
            "sequence": self.sequence,
            "sha256": self.sha256,
            "byte_size": self.byte_size,
            "source_url": self.source_url,
            "content_type": "application/json",
            "parent_reference_id": None,
            "required": True,
        }


@dataclass(frozen=True)
class PreparedObservation:
    source_key: str
    run_id: str
    scope: ReviewedScope
    options: ImportOptions
    canonical_path: Path
    canonical_sha256: str
    count: int
    references: tuple[ProofReference, ...]
    reconciliation: dict[str, Any]


class DurableObservation:
    def __init__(
        self,
        service: ArtifactService,
        source_key: str,
        run_id: str,
        max_staged_bytes: int = 2 * MAX_TOTAL_BYTES,
    ) -> None:
        config = SOURCE_CONFIGS.get(source_key)
        if config is None or not config.category:
            raise ProvenanceError("environmental_source_not_allowlisted")
        try:
            UUID(run_id)
        except ValueError:
            raise ProvenanceError("observation_run_invalid") from None
        self.service, self.source_key, self.run_id = service, source_key, run_id
        self.started = time.monotonic()
        self.bytes = 0
        self.canonical_bytes = 0
        self.max_staged_bytes = max_staged_bytes
        with service.manifest.sessions() as session:
            rows = session.execute(
                select(ArtifactReference, ArtifactBlob)
                .join(ArtifactBlob, ArtifactBlob.id == ArtifactReference.blob_id)
                .where(
                    ArtifactReference.source_key == source_key,
                    ArtifactReference.run_id == run_id,
                )
                .limit(1025)
            ).all()
        if not 2 <= len(rows) <= 1024:
            raise ProvenanceError("observation_reference_budget")
        if any(not row.ArtifactReference.required for row in rows):
            raise ProvenanceError("observation_optional_reference")
        self.references = tuple(
            ProofReference(
                row.ArtifactReference.id,
                row.ArtifactReference.artifact_type,
                self._sequence(row.ArtifactReference.logical_key),
                row.ArtifactBlob.sha256,
                row.ArtifactBlob.byte_size,
                row.ArtifactReference.source_url,
            )
            for row in rows
        )
        if len({(ref.role, ref.sequence) for ref in self.references}) != len(self.references):
            raise ProvenanceError("observation_role_repeated")

    @staticmethod
    def _sequence(value: str) -> int:
        if len(value) != 6 or any(character not in "0123456789" for character in value):
            raise ProvenanceError("observation_sequence_invalid")
        return int(value)

    def one(self, role: str, sequence: int = 0) -> ProofReference:
        refs = [ref for ref in self.references if ref.role == role and ref.sequence == sequence]
        if len(refs) != 1:
            raise ProvenanceError("observation_role_missing")
        return refs[0]

    def download(self, ref: ProofReference, path: Path, cap: int) -> None:
        blob, state = self.service.manifest.lookup(ref.id, self.service.sink_id)
        if (
            state != "verified"
            or blob.sha256 != ref.sha256
            or blob.byte_size != ref.byte_size
            or blob.byte_size > cap
        ):
            raise ProvenanceError("observation_copy_unavailable")
        digest, size = hashlib.sha256(), 0
        chunks = self.service.sink.read(blob)
        try:
            with path.open("xb") as target:
                for chunk in chunks:
                    size += len(chunk)
                    self.bytes += len(chunk)
                    if (
                        len(chunk) > CHUNK_BYTES
                        or size > ref.byte_size
                        or self.bytes > MAX_TOTAL_BYTES
                        or self.bytes + self.canonical_bytes > self.max_staged_bytes
                        or time.monotonic() - self.started > MAX_SECONDS
                    ):
                        raise ProvenanceError("observation_io_budget")
                    digest.update(chunk)
                    target.write(chunk)
            if size != ref.byte_size or digest.hexdigest() != ref.sha256:
                raise ProvenanceError("observation_bytes_changed")
        except Exception:
            path.unlink(missing_ok=True)
            raise
        finally:
            close = getattr(chunks, "close", None)
            if close is not None:
                close()

    def json(self, ref: ProofReference, path: Path, cap: int) -> dict[str, Any]:
        self.download(ref, path, cap)
        try:
            value = json.loads(
                path.read_bytes(),
                parse_constant=_reject_nonfinite_constant,
                parse_float=_parse_finite_float,
            )
        except (ValueError, UnicodeError):
            raise ProvenanceError("observation_json_invalid") from None
        if not isinstance(value, dict):
            raise ProvenanceError("observation_json_invalid")
        return value


def _prepare_observation(
    service: ArtifactService,
    source_key: str,
    run_id: str,
    destination: Path,
    max_staged_bytes: int,
) -> PreparedObservation:
    """All durable I/O and canonical serialization occur outside mutation locks."""
    observation = DurableObservation(service, source_key, run_id, max_staged_bytes)
    destination.mkdir(parents=True, exist_ok=False)
    config = SOURCE_CONFIGS[source_key]
    scope_ref, report_ref = observation.one("b02-scope"), observation.one("b02-report")
    if scope_ref.source_url != config.layer_url or report_ref.source_url != config.layer_url:
        raise ProvenanceError("observation_source_mismatch")
    scope_path = destination / "scope.json"
    observation.download(scope_ref, scope_path, MAX_REPORT_BYTES)
    scope = ReviewedScope.load(scope_path)
    report = observation.json(report_ref, destination / "report.json", MAX_REPORT_BYTES)
    base = _base_query(config, scope)
    if (
        report.get("source_key") != source_key
        or report.get("run_id") != run_id
        or report.get("source_url") != config.layer_url
        or report.get("scope_id") != scope.scope_id_for(config)
        or report.get("scope_version") != scope.version
        or report.get("raw_boundary_response_sha256") != scope.raw_boundary_response_sha256
        or report.get("boundary_algorithm") != scope.boundary_algorithm
        or report.get("where") != config.where
        or report.get("spatial_relation") != "esriSpatialRelIntersects"
        or report.get("time_window") is not None
        or report.get("boundary_sha256") != scope.boundary_sha256
        or report.get("context_sha256") != scope.context_sha256
        or report.get("coverage") != "complete"
        or report.get("canary") is not False
        or report.get("error_code")
        or report.get("rejected") != 0
    ):
        raise ProvenanceError("observation_not_complete")
    controls = report.get("control_artifacts")
    offset = config.connector_config.get("pagination") == "offset"
    roles = (
        ("initial_metadata", "initial_count", "final_count", "final_metadata")
        if offset
        else ("initial_metadata", "initial_count", "initial_ids", "final_ids")
    )
    if (
        not isinstance(controls, list)
        or not all(isinstance(item, dict) for item in controls)
        or [item.get("role") for item in controls] != list(roles)
    ):
        raise ProvenanceError("observation_controls_missing")
    payloads: dict[str, dict[str, Any]] = {}
    for sequence, descriptor in enumerate(controls):
        role = roles[sequence]
        ref = observation.one("b02-control", sequence)
        operation = (
            "metadata"
            if role.endswith("metadata")
            else ("count" if role.endswith("count") else "ids")
        )
        endpoint = config.layer_url if operation == "metadata" else config.query_url
        query = (
            {"f": "json"}
            if operation == "metadata"
            else {
                **base,
                "f": "json",
                "returnCountOnly" if operation == "count" else "returnIdsOnly": "true",
            }
        )
        expected = {
            "format": CONTROL_FORMAT,
            "role": role,
            "sequence": sequence,
            "source_key": source_key,
            "run_id": run_id,
            "scope_id": scope.scope_id_for(config),
            "scope_version": scope.version,
            "scope_query_sha256": _digest(base),
            "query_sha256": _digest(query),
            "sha256": ref.sha256,
            "bytes": ref.byte_size,
            "status": 200,
            "operation": operation,
            "url": endpoint,
            "body_encoding": "http-content-decoded",
        }
        if (
            any(descriptor.get(key) != value for key, value in expected.items())
            or descriptor.get("method") not in {"GET", "POST"}
            or ref.source_url != endpoint
        ):
            raise ProvenanceError("observation_control_binding")
        payloads[role] = observation.json(
            ref, destination / f"control-{sequence}.json", CONTROL_CAPS[operation]
        )
    if sum(ref.byte_size for ref in observation.references if ref.role == "b02-control") > (
        MAX_CONTROL_BYTES
    ):
        raise ProvenanceError("observation_control_byte_budget")
    oid = _oid_field(payloads["initial_metadata"], config)
    if report.get("object_id_field") != oid:
        raise ProvenanceError("observation_oid_field_mismatch")
    count = _count(payloads["initial_count"])
    if count > MAX_IDS:
        raise ProvenanceError("observation_id_budget")
    ids: list[int] | None = None
    if offset:
        final_metadata = payloads["final_metadata"]
        _oid_field(final_metadata, config)
        initial_edit = payloads["initial_metadata"].get("editingInfo", {}).get("lastEditDate")
        final_edit = final_metadata.get("editingInfo", {}).get("lastEditDate")
        if (
            _count(payloads["final_count"]) != count
            or initial_edit is None
            or final_edit != initial_edit
            or _digest(final_metadata) != _digest(payloads["initial_metadata"])
        ):
            raise ProvenanceError("observation_offset_changed")
        reconciliation = {"method": "offset", "count": count, "edit_version": initial_edit}
    else:
        ids = _ids(payloads["initial_ids"], oid, MAX_IDS)
        if len(ids) != count or _ids(payloads["final_ids"], oid, MAX_IDS) != ids:
            raise ProvenanceError("observation_ids_changed")
        reconciliation = {"method": "ids", "count": count, "ids_sha256": _digest(ids)}
    pages = report.get("pages")
    if (
        not isinstance(pages, list)
        or not all(isinstance(item, dict) for item in pages)
        or len(pages) > MAX_PAGE_ARTIFACTS
    ):
        raise ProvenanceError("observation_page_budget")
    permitted = (
        {("b02-scope", 0), ("b02-report", 0)}
        | {("b02-control", index) for index in range(4)}
        | {("b02-page", index) for index in range(len(pages))}
    )
    actual = {(ref.role, ref.sequence) for ref in observation.references}
    if actual - {("b02-input", 0)} != permitted:
        raise ProvenanceError("observation_required_set_mismatch")
    options = ImportOptions(
        layer_id=source_key,
        scope_id=scope.scope_id_for(config),
        scope_version=scope.version,
        id_field=oid,
        expected_count=count,
        scope_definition={
            "boundary_sha256": scope.boundary_sha256,
            "context_sha256": scope.context_sha256,
            "query_sha256": _digest(base),
        },
    )
    canonical_path = destination / "canonical.json"
    metadata = {
        "id": source_key,
        "name": config.name,
        "category": config.category,
        "source_url": config.layer_url,
        "attribution": config.attribution,
        "caveat": config.caveat or "",
        "geom_type": config.geometry_type,
    }
    seen: set[int] = set()
    with canonical_path.open("xb") as body:
        target = CanonicalWriter(body, observation)
        envelope = _canonical(metadata)
        target.write(b"[" + envelope[:-1] + b',"features":{"type":"FeatureCollection","features":[')
        first = True
        for sequence, descriptor in enumerate(pages):
            ref = observation.one("b02-page", sequence)
            if (
                descriptor.get("sha256") != ref.sha256
                or descriptor.get("bytes") != ref.byte_size
                or ref.source_url != config.query_url
            ):
                raise ProvenanceError("observation_page_binding")
            payload = observation.json(ref, destination / f"page-{sequence}.json", MAX_PAGE_BYTES)
            features = payload.get("features")
            if payload.get("type") != "FeatureCollection" or not isinstance(features, list):
                raise ProvenanceError("observation_page_invalid")
            if len(features) != descriptor.get("returned") or len(features) > 250:
                raise ProvenanceError("observation_page_count")
            for feature in features:
                identity = _feature_id(feature, oid)
                if identity in seen or len(seen) >= MAX_IDS:
                    raise ProvenanceError("observation_feature_duplicate")
                if not _geometry_ok(feature, config) or not _properties_ok(feature, config):
                    raise ProvenanceError("observation_feature_invalid")
                _prepare(feature, options, geom_type=config.geometry_type)
                seen.add(identity)
                if not first:
                    target.write(b",")
                target.write(_canonical(feature))
                first = False
            if (
                target.tell() > MAX_TOTAL_BYTES
                or time.monotonic() - observation.started > MAX_SECONDS
            ):
                raise ProvenanceError("observation_io_budget")
        target.write(b"]}}]")
    if len(seen) != count or ids is not None and sorted(seen) != ids:
        raise ProvenanceError("observation_pages_unreconciled")
    if any(report.get(key) != count for key in ("expected", "fetched", "accepted")):
        raise ProvenanceError("observation_report_counts")
    digest = hashlib.sha256()
    with canonical_path.open("rb") as source:
        while chunk := source.read(CHUNK_BYTES):
            digest.update(chunk)
    return PreparedObservation(
        source_key,
        run_id,
        scope,
        options,
        canonical_path,
        digest.hexdigest(),
        count,
        observation.references,
        reconciliation,
    )


def prepare_observation(
    service: ArtifactService,
    source_key: str,
    run_id: str,
    destination: Path,
    *,
    max_staged_bytes: int = 2 * MAX_TOTAL_BYTES,
) -> PreparedObservation:
    try:
        return _prepare_observation(service, source_key, run_id, destination, max_staged_bytes)
    except ProvenanceError:
        raise
    except ScopeError as exc:
        raise ProvenanceError(str(exc)) from None
    except ArtifactError as exc:
        raise ProvenanceError(exc.code) from None
    except (KeyError, TypeError, AttributeError, ValueError, OSError):
        raise ProvenanceError("observation_invalid") from None


class CanonicalWriter:
    def __init__(self, body: IO[bytes], observation: DurableObservation) -> None:
        self.body, self.observation = body, observation
        self.size = 0

    def write(self, data: bytes) -> None:
        self.size += len(data)
        if (
            self.size > MAX_TOTAL_BYTES
            or self.size + self.observation.bytes > self.observation.max_staged_bytes
            or time.monotonic() - self.observation.started > MAX_SECONDS
        ):
            raise ProvenanceError("observation_io_budget")
        self.body.write(data)
        self.observation.canonical_bytes = self.size

    def tell(self) -> int:
        return self.size


def upload_observation(
    service: ArtifactService,
    source_key: str,
    scope_path: Path,
    stage: Path,
) -> str:
    """Upload all captured evidence without sealing a partial required set."""
    config = SOURCE_CONFIGS.get(source_key)
    if config is None or not config.category:
        raise ProvenanceError("environmental_source_not_allowlisted")
    try:
        with service.staging_path(stage / "report.json").open("rb") as report_file:
            raw = report_file.read(MAX_REPORT_BYTES + 1)
        if len(raw) > MAX_REPORT_BYTES:
            raise ProvenanceError("observation_report_budget")
        report = json.loads(raw)
        run_id = str(UUID(report["run_id"]))
        controls, pages = report["control_artifacts"], report["pages"]
        if (
            not isinstance(controls, list)
            or len(controls) != 4
            or not isinstance(pages, list)
            or len(pages) > MAX_PAGE_ARTIFACTS
        ):
            raise ProvenanceError("observation_artifact_budget")
        items = [
            (scope_path, "b02-scope", 0, config.layer_url),
            (stage / "report.json", "b02-report", 0, config.layer_url),
        ]
        for role, descriptors in (("b02-control", controls), ("b02-page", pages)):
            for sequence, descriptor in enumerate(descriptors):
                if not isinstance(descriptor, dict):
                    raise ProvenanceError("observation_report_invalid")
                name = descriptor["path"]
                if not isinstance(name, str) or Path(name).name != name:
                    raise ProvenanceError("observation_path_invalid")
                url = (
                    config.layer_url
                    if descriptor.get("operation") == "metadata"
                    else (config.query_url)
                )
                items.append((stage / name, role, sequence, url))
    except (KeyError, TypeError, ValueError, OSError, ArtifactError) as exc:
        if isinstance(exc, ProvenanceError):
            raise
        raise ProvenanceError("observation_report_invalid") from None
    for path, role, sequence, url in items:
        try:
            service.upload_file(
                path=path,
                source_key=source_key,
                run_id=run_id,
                artifact_type=role,
                logical_key=f"{sequence:06}",
                required=True,
                content_type="application/json",
                source_url=url,
            )
        except (OSError, ArtifactError):
            raise ProvenanceError("observation_upload_failed") from None
    return run_id
