from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest
from test_scoped_arcgis import _scope

from app.ingestion.artifact_service import ArtifactService
from app.ingestion.artifact_sink import BlobIdentity
from app.ingestion.environmental_attestation import _bounded_proof_references
from app.ingestion.environmental_proof import (
    MAX_REPORT_BYTES,
    PROOF_FORMAT,
    ProofReference,
    ProvenanceError,
    prepare_observation,
    upload_observation,
)
from app.ingestion.environmental_stream import inspect_overlay_file, stream_overlay_features
from app.ingestion.scoped_arcgis import CollectionBudget, stage_scoped_source
from app.ingestion.sources.huntsville import FEMA_FLOODPLAIN_1PCT

CONFIG = FEMA_FLOODPLAIN_1PCT


def test_gate_accepts_generated_typed_reference_binding() -> None:
    reference = ProofReference(uuid4(), "b02-scope", 0, "a" * 64, 12, CONFIG.layer_url)
    assert _bounded_proof_references(
        {"format": PROOF_FORMAT, "references": [reference.binding()]}
    ) == (reference,)


@pytest.mark.parametrize(
    "binding",
    [
        None,
        [],
        {"format": "wrong"},
        {"format": "environmental-provenance-v1", "references": ["private malformed"]},
        {"format": "environmental-provenance-v1", "references": [{}] * 1025},
        {
            "format": "environmental-provenance-v1",
            "references": [{}],
            "oversized": "x" * (MAX_REPORT_BYTES + 1),
        },
    ],
)
def test_gate_proof_shapes_refuse_with_bounded_diagnostics(binding: Any) -> None:
    with pytest.raises(ProvenanceError) as refused:
        _bounded_proof_references(binding)
    assert str(refused.value) == "environmental_provenance_unavailable"


@pytest.mark.parametrize("failure", ["oversized", "descriptor", "missing"])
def test_upload_report_refuses_before_any_reference_upload(tmp_path: Path, failure: str) -> None:
    memory = MemoryService()
    stage = tmp_path / "stage"
    stage.mkdir()
    report_path = stage / "report.json"
    if failure == "oversized":
        report_path.write_bytes(b" " * (MAX_REPORT_BYTES + 1))
    elif failure == "descriptor":
        report_path.write_text(
            json.dumps(
                {
                    "run_id": str(uuid4()),
                    "control_artifacts": ["private malformed"] * 4,
                    "pages": [],
                }
            )
        )
    with pytest.raises(ProvenanceError) as refused:
        upload_observation(
            cast(ArtifactService, memory), CONFIG.key, tmp_path / "scope.json", stage
        )
    assert memory.rows == [] and memory.data == {}
    assert "private" not in str(refused.value)


class MemoryService:
    """Durable-adapter fixture; these bytes are not real upstream observations."""

    def __init__(self) -> None:
        self.data: dict[UUID, bytes] = {}
        self.rows: list[Any] = []
        self.sink_id = "a" * 64
        self.manifest = SimpleNamespace(sessions=lambda: self, lookup=self.lookup)
        self.sink = SimpleNamespace(read=self.read)

    def __enter__(self) -> MemoryService:
        return self

    def __exit__(self, *_args: Any) -> None:
        pass

    def execute(self, _statement: Any) -> Any:
        return SimpleNamespace(all=lambda: self.rows)

    def staging_path(self, path: Path) -> Path:
        return path

    def upload_file(self, **kwargs: Any) -> UUID:
        data = kwargs["path"].read_bytes()
        identity = uuid4()
        self.data[identity] = data
        reference = SimpleNamespace(
            id=identity,
            artifact_type=kwargs["artifact_type"],
            logical_key=kwargs["logical_key"],
            source_url=kwargs["source_url"],
            required=True,
        )
        blob = SimpleNamespace(sha256=hashlib.sha256(data).hexdigest(), byte_size=len(data))
        self.rows.append(SimpleNamespace(ArtifactReference=reference, ArtifactBlob=blob))
        return identity

    def lookup(self, identity: UUID, _sink: str) -> tuple[BlobIdentity, str]:
        row = next(row for row in self.rows if row.ArtifactReference.id == identity)
        return BlobIdentity(row.ArtifactBlob.sha256, row.ArtifactBlob.byte_size), "verified"

    def read(self, blob: BlobIdentity):  # type: ignore[no-untyped-def]
        for identity, data in self.data.items():
            row = next(row for row in self.rows if row.ArtifactReference.id == identity)
            if row.ArtifactBlob.sha256 == blob.sha256:
                yield data
                return
        raise AssertionError("missing fixture blob")


def capture(
    tmp_path: Path, *, changed_ids: bool = False, count: int = 70
) -> tuple[MemoryService, str, dict[str, Any]]:
    scope = _scope(tmp_path)
    ids_calls = 0

    def response(request: httpx.Request) -> httpx.Response:
        nonlocal ids_calls
        params = dict(request.url.params)
        if request.url.path.endswith("/7"):
            return httpx.Response(
                200,
                json={
                    "geometryType": "esriGeometryPolygon",
                    "supportedQueryFormats": "geoJSON",
                    "extent": {"spatialReference": {"wkid": 102629}},
                    "objectIdField": "OBJECTID",
                    "fields": [{"name": "OBJECTID", "type": "esriFieldTypeOID"}],
                    "editingInfo": {"lastEditDate": 1234},
                },
            )
        if params.get("returnCountOnly") == "true":
            return httpx.Response(200, json={"count": count})
        if params.get("returnIdsOnly") == "true":
            ids_calls += 1
            values = list(range(count))
            if changed_ids and ids_calls > 1:
                values[-1] = 100
            return httpx.Response(200, json={"objectIds": values})
        features = []
        for identity in map(int, params["objectIds"].split(",")):
            ring = [[-86.6, 34.4], [-86.5, 34.4], [-86.5, 34.5], [-86.6, 34.5], [-86.6, 34.4]]
            geometry: dict[str, Any] = {"type": "Polygon", "coordinates": [ring]}
            if identity == 0:
                second_ring = [[x, y + 0.2] for x, y in ring]
                geometry = {"type": "MultiPolygon", "coordinates": [[ring], [second_ring]]}
            if identity == 1:
                hole = [
                    [-86.58, 34.42],
                    [-86.58, 34.44],
                    [-86.56, 34.44],
                    [-86.56, 34.42],
                    [-86.58, 34.42],
                ]
                geometry["coordinates"].append(hole)
            features.append(
                {
                    "type": "Feature",
                    "properties": {"OBJECTID": identity, "FLD_ZONE": "AE"},
                    "geometry": geometry,
                }
            )
        return httpx.Response(200, json={"type": "FeatureCollection", "features": features})

    with httpx.Client(transport=httpx.MockTransport(response)) as client:
        report = stage_scoped_source(
            CONFIG,
            scope,
            tmp_path / "stage",
            client=client,
            budget=CollectionBudget(min_interval_seconds=0),
        )
    memory = MemoryService()
    run_id = upload_observation(
        cast(ArtifactService, memory),
        CONFIG.key,
        tmp_path / "reviewed-scope.json",
        tmp_path / "stage",
    )
    return memory, run_id, report


def test_durable_controls_generate_exact_deterministic_p03_envelope(tmp_path: Path) -> None:
    service, run, report = capture(tmp_path)
    assert report["coverage"] == "complete" and len(report["pages"]) == 3
    first = prepare_observation(cast(ArtifactService, service), CONFIG.key, run, tmp_path / "one")
    second = prepare_observation(cast(ArtifactService, service), CONFIG.key, run, tmp_path / "two")
    assert first.canonical_path.read_bytes() == second.canonical_path.read_bytes()
    checksum, overlays = inspect_overlay_file(first.canonical_path)
    assert checksum == first.canonical_sha256 and overlays[0].feature_count == 70
    features = list(
        stream_overlay_features(first.canonical_path, index=0, expected_checksum=checksum)
    )
    assert features[0]["geometry"]["type"] == "MultiPolygon"
    assert [feature["properties"]["OBJECTID"] for feature in features] == list(range(70))
    assert first.reconciliation["count"] == 70 and first.options.coverage == "unknown"
    assert len(first.references) == 9


def test_complete_zero_feature_observation_has_original_controls(tmp_path: Path) -> None:
    service, run, report = capture(tmp_path, count=0)
    assert report["coverage"] == "complete" and report["pages"] == []
    assert len(report["control_artifacts"]) == 4
    prepared = prepare_observation(
        cast(ArtifactService, service), CONFIG.key, run, tmp_path / "empty"
    )
    checksum, overlays = inspect_overlay_file(prepared.canonical_path)
    assert checksum == prepared.canonical_sha256 and overlays[0].feature_count == 0
    assert prepared.count == 0 and prepared.reconciliation["count"] == 0
    assert len(prepared.references) == 6 and prepared.options.coverage == "unknown"


def test_durable_preparation_enforces_its_own_staging_cap(tmp_path: Path) -> None:
    service, run, _report = capture(tmp_path)
    destination = tmp_path / "bounded"
    with pytest.raises(ProvenanceError):
        prepare_observation(
            cast(ArtifactService, service), CONFIG.key, run, destination, max_staged_bytes=1
        )
    assert sum(path.stat().st_size for path in destination.rglob("*") if path.is_file()) <= 1


@pytest.mark.parametrize(
    "mutation",
    [
        "bytes",
        "role",
        "query",
        "source",
        "count",
        "ids",
        "page",
        "canary",
        "missing",
        "extra",
        "scope_claim",
        "control_item",
        "page_item",
    ],
)
def test_durable_proof_refuses_forged_or_changed_evidence(tmp_path: Path, mutation: str) -> None:
    memory, run, original = capture(tmp_path)
    assert original["coverage"] == "complete"
    row = next(row for row in memory.rows if row.ArtifactReference.artifact_type == "b02-report")
    if mutation == "bytes":
        memory.data[row.ArtifactReference.id] += b" "
    elif mutation == "missing":
        memory.rows.pop()
    elif mutation == "extra":
        memory.rows.append(
            SimpleNamespace(
                ArtifactReference=SimpleNamespace(
                    id=uuid4(),
                    artifact_type="unexpected",
                    logical_key="000000",
                    source_url=CONFIG.layer_url,
                    required=True,
                ),
                ArtifactBlob=SimpleNamespace(sha256="b" * 64, byte_size=0),
            )
        )
    else:
        report = json.loads(memory.data[row.ArtifactReference.id])
        if mutation == "role":
            report["control_artifacts"][2]["role"] = "final_count"
        elif mutation == "query":
            report["control_artifacts"][1]["query_sha256"] = "0" * 64
        elif mutation == "source":
            report["source_url"] = "https://other.invalid/0"
        elif mutation == "count":
            report["accepted"] -= 1
        elif mutation == "ids":
            control = next(
                item
                for item in memory.rows
                if item.ArtifactReference.artifact_type == "b02-control"
                and item.ArtifactReference.logical_key == "000003"
            )
            raw = json.dumps({"objectIds": [*range(69), 100]}).encode()
            control.ArtifactBlob.sha256 = hashlib.sha256(raw).hexdigest()
            control.ArtifactBlob.byte_size = len(raw)
            memory.data[control.ArtifactReference.id] = raw
            report["control_artifacts"][3].update(
                sha256=control.ArtifactBlob.sha256, bytes=len(raw)
            )
        elif mutation == "page":
            report["pages"].reverse()
        elif mutation == "canary":
            report["canary"] = True
        elif mutation == "scope_claim":
            report["where"] = "private contradictory selector"
        elif mutation == "control_item":
            report["control_artifacts"][1] = "private malformed control"
        elif mutation == "page_item":
            report["pages"][0] = "private malformed page"
        raw = json.dumps(report).encode()
        memory.data[row.ArtifactReference.id] = raw
        row.ArtifactBlob.sha256, row.ArtifactBlob.byte_size = (
            hashlib.sha256(raw).hexdigest(),
            len(raw),
        )
    with pytest.raises(ProvenanceError) as failure:
        prepare_observation(cast(ArtifactService, memory), CONFIG.key, run, tmp_path / "refused")
    assert "private" not in str(failure.value)
