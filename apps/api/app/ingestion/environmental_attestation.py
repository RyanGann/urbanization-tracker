"""Shadow provenance preparation and bounded database-only proof gates."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, replace
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, inspect, select, text
from sqlalchemy.orm import Session

from app.ingestion.artifact_manifest import _lock_observation, require_verified_references
from app.ingestion.artifact_service import ArtifactService
from app.ingestion.artifact_sink import hash_stream
from app.ingestion.environmental_import import (
    IMPORT_FORMAT,
    _include_bounds,
    _prepare,
    data_version,
    import_environmental_file,
    import_session,
)
from app.ingestion.environmental_proof import (
    MAX_SECONDS,
    PROOF_FORMAT,
    PreparedObservation,
    ProofReference,
    ProvenanceError,
)
from app.ingestion.environmental_stream import stream_overlay_features
from app.ingestion.scoped_arcgis import SOURCE_CONFIGS, _digest
from app.models import (
    ArtifactBlob,
    ArtifactReference,
    ArtifactRunSeal,
    EnvironmentalAttestation,
    EnvironmentalAttestationReference,
    EnvironmentalFeature,
    EnvironmentalLayer,
)
from app.transactional_store import CollectionUnitOfWork

UNBOUND_PARENT_COLUMNS = frozenset(
    {
        "loaded_at",
        "import_started_at",
        "import_finished_at",
        "canonical_revision",
    }
)


def layer_binding(layer: EnvironmentalLayer) -> dict[str, Any]:
    return {
        column.key: getattr(layer, column.key)
        for column in inspect(EnvironmentalLayer).columns
        if column.key not in UNBOUND_PARENT_COLUMNS
    }


@dataclass(frozen=True)
class PreparedAttestation:
    observation: PreparedObservation
    layer_id: int
    revision: int
    layer: dict[str, Any]

    def binding(self, sink_id: str) -> dict[str, Any]:
        refs = sorted(self.observation.references, key=lambda ref: (ref.role, ref.sequence))
        return {
            "format": PROOF_FORMAT,
            "source_key": self.observation.source_key,
            "run_id": self.observation.run_id,
            "sink_id": sink_id,
            "canonical_revision": self.revision,
            "layer": self.layer,
            "reconciliation": self.observation.reconciliation,
            "references": [ref.binding() for ref in refs],
            "required_set_sha256": _digest(
                sorted((str(ref.id), ref.sha256, ref.byte_size) for ref in refs)
            ),
        }


def import_and_validate(
    service: ArtifactService,
    observation: PreparedObservation,
) -> PreparedAttestation:
    """Ordinary P03 import, then compare actual SQL geometry/attrs outside C02."""
    with observation.canonical_path.open("rb") as source:
        blob = hash_stream(source)
    if blob.sha256 != observation.canonical_sha256:
        raise ProvenanceError("canonical_input_changed")
    input_id = service.upload_file(
        path=observation.canonical_path,
        source_key=observation.source_key,
        run_id=observation.run_id,
        artifact_type="b02-input",
        logical_key="000000",
        required=True,
        content_type="application/json",
        source_url=SOURCE_CONFIGS[observation.source_key].layer_url,
    )
    input_ref = ProofReference(
        input_id,
        "b02-input",
        0,
        blob.sha256,
        blob.byte_size,
        SOURCE_CONFIGS[observation.source_key].layer_url,
    )
    prior = [ref for ref in observation.references if ref.role == "b02-input"]
    if prior and prior != [input_ref]:
        raise ProvenanceError("canonical_reference_changed")
    observation = replace(
        observation,
        references=tuple(ref for ref in observation.references if ref.role != "b02-input")
        + (input_ref,),
    )
    imported = import_environmental_file(
        observation.canonical_path, observation.options, dry_run=False
    )
    version = data_version(blob.sha256, observation.options)
    if (
        imported["status"] != "validated"
        or imported["accepted"] != observation.count
        or imported["rejected"]
        or imported["duplicates"]
        or imported["data_version"] != version
    ):
        raise ProvenanceError("canonical_import_invalid")
    started = time.monotonic()
    with import_session(observation.source_key, version) as session:
        session.execute(text("SET LOCAL statement_timeout = '30s'"))
        session.execute(text("SET LOCAL lock_timeout = '1500ms'"))
        layer = session.scalar(
            select(EnvironmentalLayer).where(
                EnvironmentalLayer.layer_key == observation.source_key,
                EnvironmentalLayer.data_version == version,
            )
        )
        if layer is None:
            raise ProvenanceError("canonical_layer_missing")
        config = SOURCE_CONFIGS[observation.source_key]
        expected_parent: dict[str, Any] = {
            "name": config.name,
            "category": config.category,
            "source_url": config.layer_url,
            "license_notes": config.attribution,
            "geom_type": config.geometry_type,
            "source_id": None,
            "version": None,
            "importer_format": IMPORT_FORMAT,
            "expected_count": observation.count,
            "seen_count": observation.count,
            "accepted_count": observation.count,
            "rejected_count": 0,
            "duplicate_count": 0,
            "import_checkpoint": observation.count,
            "diagnostics_json": {"reasons": {}, "samples": []},
        }
        if any(getattr(layer, key) != value for key, value in expected_parent.items()):
            raise ProvenanceError("canonical_layer_changed")
        revision, binding = layer.canonical_revision, layer_binding(layer)
        if (
            layer.scope_json != observation.options.scope()
            or layer.source_checksum != blob.sha256
            or layer.coverage_status != "unknown"
            or layer.import_status != "validated"
        ):
            raise ProvenanceError("canonical_layer_changed")
        count = session.scalar(
            select(func.count())
            .select_from(EnvironmentalFeature)
            .where(
                EnvironmentalFeature.environmental_layer_id == layer.id,
            )
        )
        if count != observation.count:
            raise ProvenanceError("canonical_feature_count")
        seen: set[str] = set()
        expected_bounds: dict[str, Any] = {"bounds": None}
        for feature in stream_overlay_features(
            observation.canonical_path, index=0, expected_checksum=blob.sha256
        ):
            expected = _prepare(feature, observation.options, geom_type=layer.geom_type)
            identity = expected["source_id"]
            if identity in seen:
                raise ProvenanceError("canonical_source_duplicate")
            seen.add(identity)
            # Exact equality after the SAME parser used by P03; this compares
            # coordinates/order/SRID, not topology-only ST_Equals or JSON↔WKB hashes.
            row = session.execute(
                text("""
                SELECT import_managed, import_fingerprint, attributes_json, name,
                       ST_AsEWKB(geometry) = ST_AsEWKB(ST_GeomFromGeoJSON(:geometry)) AS same_geom
                       , ST_XMin(Box3D(geometry)), ST_YMin(Box3D(geometry)),
                       ST_XMax(Box3D(geometry)), ST_YMax(Box3D(geometry))
                FROM environmental_features
                WHERE environmental_layer_id = :layer AND source_feature_id = :source
                  AND import_managed IS TRUE
            """),
                {"geometry": expected["geometry"], "layer": layer.id, "source": identity},
            ).all()
            if (
                len(row) != 1
                or not row[0].import_managed
                or not row[0].same_geom
                or row[0].import_fingerprint != expected["fingerprint"]
                or row[0].attributes_json != expected["attributes"]
                or row[0].name is not None
            ):
                raise ProvenanceError("canonical_feature_changed")
            _include_bounds(expected_bounds, row[0][5:])
            if time.monotonic() - started > MAX_SECONDS:
                raise ProvenanceError("canonical_validation_budget")
        session.expire(layer)
        if (
            len(seen) != count
            or layer.canonical_revision != revision
            or layer_binding(layer) != binding
            or layer.bounds_json != expected_bounds["bounds"]
        ):
            raise ProvenanceError("canonical_revision_changed")
        return PreparedAttestation(observation, layer.id, revision, binding)


def _lock_reference_identities(
    session: Session,
    refs: tuple[ProofReference, ...],
    source_key: str,
    run_id: str,
) -> None:
    _lock_observation(session, source_key, run_id)
    session.execute(
        text("SELECT b02_lock_observation(:source, :run)"), {"source": source_key, "run": run_id}
    )
    rows = session.scalars(
        select(ArtifactReference)
        .where(
            ArtifactReference.id.in_([ref.id for ref in refs]),
        )
        .order_by(ArtifactReference.id)
        .with_for_update()
    ).all()
    if len(rows) != len(refs):
        raise ProvenanceError("proof_reference_missing")
    blobs = session.scalars(
        select(ArtifactBlob)
        .where(
            ArtifactBlob.id.in_([row.blob_id for row in rows]),
        )
        .order_by(ArtifactBlob.id)
        .with_for_update()
    ).all()
    by_id = {blob.id: blob for blob in blobs}
    expected = {ref.id: ref for ref in refs}
    for row in rows:
        ref, blob = expected[row.id], by_id[row.blob_id]
        if (
            row.source_key != source_key
            or row.run_id != run_id
            or not row.required
            or row.artifact_type != ref.role
            or row.logical_key != f"{ref.sequence:06}"
            or row.source_url != ref.source_url
            or row.content_type != "application/json"
            or row.parent_reference_id is not None
            or blob.sha256 != ref.sha256
            or blob.byte_size != ref.byte_size
        ):
            raise ProvenanceError("proof_reference_changed")


def attest_prepared(service: ArtifactService, prepared: PreparedAttestation) -> UUID:
    """Short atomic parent→identity→copy locking; no file/store traversal here."""
    observation = prepared.observation
    binding = prepared.binding(service.sink_id)
    if len(json.dumps(binding).encode()) > 1024 * 1024:
        raise ProvenanceError("proof_binding_budget")
    digest = _digest(binding)
    with service.manifest.sessions.begin() as session:
        with CollectionUnitOfWork(session).canonical_mutation():
            layer = session.scalar(
                select(EnvironmentalLayer)
                .where(
                    EnvironmentalLayer.id == prepared.layer_id,
                )
                .with_for_update()
            )
            if (
                layer is None
                or layer.canonical_revision != prepared.revision
                or layer_binding(layer) != prepared.layer
            ):
                raise ProvenanceError("canonical_revision_changed")
            refs = observation.references
            _lock_reference_identities(session, refs, observation.source_key, observation.run_id)
            seal = session.scalar(
                select(ArtifactRunSeal)
                .where(
                    ArtifactRunSeal.source_key == observation.source_key,
                    ArtifactRunSeal.run_id == observation.run_id,
                )
                .with_for_update()
            )
            require_verified_references(
                session,
                reference_ids=tuple(ref.id for ref in refs),
                source_key=observation.source_key,
                run_id=observation.run_id,
                sink_id=service.sink_id,
            )
            if seal is None:
                seal = session.get(ArtifactRunSeal, (observation.source_key, observation.run_id))
            assert seal is not None
            if seal.required_set_sha256 != binding["required_set_sha256"]:
                raise ProvenanceError("proof_seal_changed")
            prior = session.scalar(
                select(EnvironmentalAttestation).where(
                    EnvironmentalAttestation.environmental_layer_id == layer.id,
                )
            )
            if prior is not None:
                if prior.proof_sha256 != digest or prior.binding_json != binding:
                    raise ProvenanceError("immutable_proof_conflict")
                return prior.id
            proof = EnvironmentalAttestation(
                id=uuid4(),
                environmental_layer_id=layer.id,
                source_key=observation.source_key,
                run_id=observation.run_id,
                sink_id=service.sink_id,
                canonical_revision=prepared.revision,
                proof_sha256=digest,
                binding_json=binding,
            )
            session.add(proof)
            session.flush()
            session.add_all(
                [
                    EnvironmentalAttestationReference(
                        attestation_id=proof.id,
                        reference_id=ref.id,
                        role=ref.role,
                        sequence=ref.sequence,
                    )
                    for ref in refs
                ]
            )
            session.flush()
            return proof.id


def require_environmental_provenance(
    session: Session,
    environmental_layer_id: int,
    expected_data_version: str,
    expected_input_checksum: str,
    attestation_digest: str,
    *,
    expected_sink_id: str,
) -> EnvironmentalAttestation:
    """DB-only gate; establishes/reuses C02 lock and never creates a missing seal."""
    CollectionUnitOfWork(session).acquire_canonical_mutation_lock()
    layer = session.scalar(
        select(EnvironmentalLayer)
        .where(
            EnvironmentalLayer.id == environmental_layer_id,
        )
        .with_for_update()
    )
    proof = session.scalar(
        select(EnvironmentalAttestation).where(
            EnvironmentalAttestation.environmental_layer_id == environmental_layer_id,
            text("octet_length(environmental_attestations.binding_json::text) <= 1048576"),
        )
    )
    refs = _bounded_proof_references(proof.binding_json if proof is not None else None)
    if (
        layer is None
        or proof is None
        or layer.data_version != expected_data_version
        or layer.source_checksum != expected_input_checksum
        or layer.import_status != "validated"
        or proof.proof_sha256 != attestation_digest
        or proof.sink_id != expected_sink_id
        or _digest(proof.binding_json) != attestation_digest
        or proof.canonical_revision != layer.canonical_revision
        or proof.binding_json.get("layer") != layer_binding(layer)
        or proof.binding_json.get("source_key") != proof.source_key
        or proof.binding_json.get("run_id") != proof.run_id
        or proof.binding_json.get("sink_id") != proof.sink_id
    ):
        raise ProvenanceError("environmental_provenance_unavailable")
    _lock_reference_identities(session, refs, proof.source_key, proof.run_id)
    links = session.scalars(
        select(EnvironmentalAttestationReference)
        .where(
            EnvironmentalAttestationReference.attestation_id == proof.id,
        )
        .limit(1025)
    ).all()
    seal = session.get(ArtifactRunSeal, (proof.source_key, proof.run_id))
    if (
        {(link.reference_id, link.role, link.sequence) for link in links}
        != {(ref.id, ref.role, ref.sequence) for ref in refs}
        or seal is None
        or seal.required_set_sha256 != proof.binding_json.get("required_set_sha256")
    ):
        raise ProvenanceError("environmental_provenance_unavailable")
    require_verified_references(
        session,
        reference_ids=tuple(ref.id for ref in refs),
        source_key=proof.source_key,
        run_id=proof.run_id,
        sink_id=proof.sink_id,
    )
    return proof


def _bounded_proof_references(binding: Any) -> tuple[ProofReference, ...]:
    """Refuse corrupt retained shapes before hashing or reconstructing identities."""
    try:
        if not isinstance(binding, dict) or binding.get("format") != PROOF_FORMAT:
            raise ValueError
        items = binding.get("references")
        if not isinstance(items, list) or not 1 <= len(items) <= 1024:
            raise ValueError
        if len(json.dumps(binding, ensure_ascii=False, allow_nan=False).encode()) > 1048576:
            raise ValueError
        refs = []
        for item in items:
            if not isinstance(item, dict):
                raise ValueError
            if (
                item.get("role")
                not in {"b02-scope", "b02-report", "b02-control", "b02-page", "b02-input"}
                or type(item.get("sequence")) is not int
                or not 0 <= item["sequence"] <= 999999
                or type(item.get("byte_size")) is not int
                or not 0 <= item["byte_size"] <= 1073741824
                or not isinstance(item.get("sha256"), str)
                or len(item["sha256"]) != 64
                or any(char not in "0123456789abcdef" for char in item["sha256"])
                or not isinstance(item.get("source_url"), str)
                or len(item["source_url"]) > 4096
                or not isinstance(item.get("id"), str)
                or item.get("required") is not True
                or item.get("content_type") != "application/json"
                or item.get("parent_reference_id") is not None
            ):
                raise ValueError
            refs.append(
                ProofReference(
                    UUID(item["id"]),
                    item["role"],
                    item["sequence"],
                    item["sha256"],
                    item["byte_size"],
                    item["source_url"],
                )
            )
        if len({ref.id for ref in refs}) != len(refs):
            raise ValueError
        return tuple(refs)
    except (KeyError, TypeError, ValueError, RecursionError):
        raise ProvenanceError("environmental_provenance_unavailable") from None
