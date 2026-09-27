"""Real PostGIS shadow-display replay, kill/resume and geometry acceptance."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from html import escape
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.db import SessionLocal
from app.ingestion import display_builder
from app.ingestion.display_builder import DisplayBuildError, build_environmental_display

LAYER = "p04a_synthetic_wetland"
VERSION = "a" * 64


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _fixture() -> list[tuple[str, dict]]:
    outer = [
        [-86.8, 34.7], [-86.5, 34.7], [-86.5, 34.9], [-86.8, 34.9], [-86.8, 34.7],
    ]
    hole = [
        [-86.74, 34.76], [-86.74, 34.83], [-86.65, 34.83],
        [-86.65, 34.76], [-86.74, 34.76],
    ]
    multipolygon = [
        [[[-86.49, 34.72], [-86.45, 34.72], [-86.45, 34.76],
          [-86.49, 34.76], [-86.49, 34.72]]],
        [[[-86.43, 34.72], [-86.39, 34.72], [-86.39, 34.76],
          [-86.43, 34.76], [-86.43, 34.72]]],
    ]
    channel = [
        [-86.38, 34.7], [-86.28, 34.7], [-86.28, 34.7015],
        [-86.38, 34.7015], [-86.38, 34.7],
    ]
    adjacent = [
        [-86.5, 34.7], [-86.4, 34.7], [-86.4, 34.9], [-86.5, 34.9], [-86.5, 34.7],
    ]
    # A dense boundary forces ST_Subdivide at the highest zoom band.
    import math

    dense = [
        [-86.18 + 0.04 * math.cos(i * 2 * math.pi / 600),
         34.75 + 0.04 * math.sin(i * 2 * math.pi / 600)]
        for i in range(600)
    ]
    dense.append(dense[0])
    return [
        ("hole", {"type": "Polygon", "coordinates": [outer, hole]}),
        ("multipart", {"type": "MultiPolygon", "coordinates": multipolygon}),
        ("channel", {"type": "Polygon", "coordinates": [channel]}),
        ("adjacent", {"type": "Polygon", "coordinates": [adjacent]}),
        ("dense", {"type": "Polygon", "coordinates": [dense]}),
    ]


def _seed_layer(layer_key: str, version: str, shapes: list[tuple[str, dict]]) -> int:
    with SessionLocal.begin() as session:
        layer_id = session.scalar(text("""
            INSERT INTO environmental_layers
                (name, category, source_url, geom_type, layer_key, data_version,
                 source_checksum, importer_format, scope_json, import_status,
                 coverage_status, expected_count, seen_count, accepted_count,
                 rejected_count, duplicate_count, import_checkpoint)
            VALUES ('P04a synthetic', 'wetlands', 'https://example.test/p04a',
                    'polygon', :layer_key, :version, :source_checksum,
                    'environmental-v1', CAST(:scope AS json), 'validated', 'unknown',
                    :count, :count, :count, 0, 0, :count)
            RETURNING id
        """), {
            "layer_key": layer_key, "version": version,
            "source_checksum": "f" * 64, "scope": json.dumps({"fixture": True}),
            "count": len(shapes),
        })
        for source_id, geometry in shapes:
            session.execute(text("""
                INSERT INTO environmental_features
                    (environmental_layer_id, source_feature_id, attributes_json,
                     import_managed, import_fingerprint, geometry)
                VALUES (:layer_id, :source_id, CAST('{}' AS json), true,
                        :fingerprint, ST_GeomFromGeoJSON(:geometry))
            """), {
                "layer_id": layer_id, "source_id": source_id,
                "fingerprint": _digest([source_id, geometry]),
                "geometry": json.dumps(geometry),
            })
    return int(layer_id)


def _canonical_hash(layer_id: int) -> str:
    with SessionLocal() as session:
        rows = session.execute(text("""
            SELECT source_feature_id, ST_AsEWKB(geometry) AS ewkb
            FROM environmental_features WHERE environmental_layer_id = :id
            ORDER BY source_feature_id
        """), {"id": layer_id})
        digest = hashlib.sha256()
        for source_id, ewkb in rows:
            digest.update(source_id.encode())
            digest.update(bytes(ewkb))
        return digest.hexdigest()


def _screening(layer_id: int) -> int:
    with SessionLocal() as session:
        return int(session.scalar(text("""
            SELECT count(*) FROM environmental_features
            WHERE environmental_layer_id = :id
              AND ST_Intersects(geometry, ST_SetSRID(ST_MakePoint(-86.55, 34.75), 4326))
        """), {"id": layer_id}) or 0)


def _part_hash(build_id: int) -> str:
    with SessionLocal() as session:
        rows = session.execute(text("""
            SELECT band_key, source_feature_id, part_number,
                   geometry_sha256, ST_AsEWKB(geometry)
            FROM environmental_display_parts WHERE build_id = :id
            ORDER BY band_key, source_feature_id COLLATE "C", part_number
        """), {"id": build_id})
        digest = hashlib.sha256()
        for band, feature_id, number, part_sha, ewkb in rows:
            assert hashlib.sha256(bytes(ewkb)).hexdigest() == part_sha
            digest.update(f"{band}:{feature_id}:{number}:{part_sha}\n".encode())
        return digest.hexdigest()


def _build_id(layer_id: int) -> int:
    with SessionLocal() as session:
        result = session.scalar(text("""
            SELECT id FROM environmental_display_builds WHERE environmental_layer_id = :id
        """), {"id": layer_id})
        assert result is not None
        return int(result)


def _checkpoint_snapshot(build_id: int) -> tuple:
    with SessionLocal() as session:
        bands = session.execute(text("""
            SELECT band_key, status, checkpoint_feature_id, processed_count,
                   part_count, collapsed_count, invalid_count,
                   checkpoint_sha256, parts_sha256
            FROM environmental_display_bands WHERE build_id = :id ORDER BY band_key
        """), {"id": build_id}).all()
        results = session.scalar(text("""
            SELECT count(*) FROM environmental_display_feature_results WHERE build_id = :id
        """), {"id": build_id})
    return tuple(tuple(row) for row in bands), results, _part_hash(build_id)


def _visual_samples(build_id: int, output: Path) -> None:
    """Retain fill-only geometry diagnostics; no tile service or public writes."""
    with SessionLocal() as session:
        rows = session.execute(text("""
            SELECT band_key, source_feature_id, ST_AsGeoJSON(geometry, 9)
            FROM environmental_display_parts WHERE build_id = :id
            ORDER BY band_key, source_feature_id, part_number
        """), {"id": build_id}).all()
    shapes = [(band, source, json.loads(geometry)["coordinates"])
              for band, source, geometry in rows]
    points = [point for _, _, rings in shapes for ring in rings for point in ring]
    west, east = min(p[0] for p in points), max(p[0] for p in points)
    south, north = min(p[1] for p in points), max(p[1] for p in points)
    scale = min(920 / (east - west), 230 / (north - south))
    colors = dict(hole="#368d9a", multipart="#986cc2", channel="#d47934",
                  adjacent="#82a951", dense="#486cbd")
    svg = ['<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="1580" '
           'viewBox="0 0 1000 1580">', '<rect width="1000" height="1580" fill="#f5f6f8"/>',
           '<g font-family="Arial,sans-serif" fill="#1b2634">',
           '<text x="30" y="30" font-size="20">P04a shadow display: fill-only samples</text>',
           '<text x="30" y="54" font-size="13">Projected display units; generalized geometry '
           'is not property-decision precision. No per-part outlines.</text>']
    for index, band in enumerate(display_builder.BANDS):
        top = 80 + index * 290
        svg.append(f'<text x="30" y="{top}" font-size="16">{escape(band.key)}: '
                   f'{band.tolerance_m} projected metre tolerance</text>')
        for key, source, rings in shapes:
            if key != band.key:
                continue
            path = " ".join(
                "M " + " L ".join(
                    f"{40 + (x - west) * scale:.3f},{top + 25 + (north - y) * scale:.3f}"
                    for x, y in ring
                ) + " Z" for ring in rings
            )
            svg.append(f'<path d="{path}" fill="{colors[source]}" fill-rule="evenodd"/>')
    for index, (source, color) in enumerate(colors.items()):
        x = 30 + index * 185
        svg.append(f'<rect x="{x}" y="1530" width="14" height="14" fill="{color}"/>')
        svg.append(f'<text x="{x + 21}" y="1542" font-size="13">{source}</text>')
    svg.append('<text x="30" y="1570" font-size="12">Hole rings use evenodd fill; '
               'topology preservation is per source feature '
               'and does not promise shared edges.</text>')
    svg.append('</g></svg>')
    (output / "fill-only-bands.svg").write_text("\n".join(svg) + "\n")


def _selective_plan(build_id: int) -> object:
    """Unvalidated background rows isolate default-planner spatial selectivity."""
    background = "p04a_plan_background"
    background_version = "e" * 64
    layer_id = _seed_layer(background, background_version, _fixture()[:1])
    with SessionLocal() as session:
        layer = display_builder._canonical_layer(session, background, background_version)
        snapshot = display_builder._source_snapshot(session, layer)
        backend = display_builder._backend_version(session)
        version = display_builder.display_version(background_version, snapshot, backend)
        build, _ = display_builder._ensure_build(session, layer, version, snapshot, backend)
        background_build_id = build.id
        feature_id = session.scalar(text("""
            SELECT id FROM environmental_features WHERE environmental_layer_id = :id
        """), {"id": layer_id})
        session.execute(text("""
            INSERT INTO environmental_display_parts
                (build_id, environmental_feature_id, band_key, source_feature_id,
                 part_number, geometry_sha256, geometry)
            SELECT :background_build_id, :feature_id, 'z17_18', 'hole', g,
                   :placeholder, ST_Translate(p.geometry,
                       (g % 100) * 100000 - 5000000, (g / 100) * 100000 - 3000000)
            FROM generate_series(1, 6000) AS g
            CROSS JOIN LATERAL (
                SELECT geometry FROM environmental_display_parts
                WHERE build_id = :template AND band_key = 'z17_18'
                ORDER BY id LIMIT 1
            ) AS p
        """), {"background_build_id": background_build_id, "feature_id": feature_id,
               "placeholder": "0" * 64, "template": build_id})
        # These intentionally synthetic plan rows stay an incomplete shadow
        # fixture, never a validated derivative and never an activation input.
        session.execute(text("ANALYZE environmental_display_parts"))
        plan = session.scalar(text("""
            EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
            SELECT id FROM environmental_display_parts
            WHERE build_id = :id AND band_key = 'z17_18'
              AND geometry && ST_MakeEnvelope(-96e5, 40e5, -95e5, 41e5, 3857)
        """), {"id": background_build_id})
        assert "ix_environmental_display_parts_geometry" in json.dumps(plan)
        assert build.status == "building"
        session.commit()
        return plan


def _kill_after_first_checkpoint(output: Path) -> None:
    sentinel = output / "checkpoint-ready"
    code = """
import sys, time
from pathlib import Path
from app.ingestion.display_builder import build_environmental_display
def pause(batch):
    if batch == 1:
        Path(sys.argv[1]).write_text('committed')
        time.sleep(3600)
build_environmental_display(sys.argv[2], sys.argv[3], batch_size=2, after_checkpoint=pause)
"""
    child = subprocess.Popen(
        [sys.executable, "-c", code, str(sentinel), LAYER, VERSION],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 45
        while not sentinel.exists():
            if child.poll() is not None:
                raise AssertionError("display builder child exited before a checkpoint")
            if time.monotonic() >= deadline:
                raise AssertionError("display builder checkpoint timed out")
            time.sleep(0.1)
        child.kill()
        child.wait(timeout=10)
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=10)


def run(output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    fixture = _fixture()
    layer_id = _seed_layer(LAYER, VERSION, fixture)
    original_hash = _canonical_hash(layer_id)
    original_screening = _screening(layer_id)
    with SessionLocal() as session:
        metadata = display_builder._next_features(session, layer_id, 0, 64)
        assert len(metadata) == len(fixture)
        assert all("input_ewkb" not in feature for feature in metadata)
    with SessionLocal() as session:
        catalog_before = session.scalar(text("""
            SELECT payload_json::text FROM processed_collection_items
            WHERE collection_name = 'map_layer_catalog' AND item_id = 'latest'
        """))
    _kill_after_first_checkpoint(output)
    with SessionLocal() as session:
        building = session.execute(text("""
            SELECT b.status, sum(d.processed_count), sum(d.part_count)
            FROM environmental_display_builds b
            JOIN environmental_display_bands d ON d.build_id = b.id
            WHERE b.environmental_layer_id = :id GROUP BY b.status
        """), {"id": layer_id}).one()
    assert building[0] == "building" and building[1] == 2
    assert _canonical_hash(layer_id) == original_hash
    checkpoint_before = _checkpoint_snapshot(_build_id(layer_id))
    original_project = display_builder._simplified
    timeout_feature_id = metadata[3]["id"]

    def statement_timeout(session, feature_id, tolerance):
        if feature_id == timeout_feature_id:
            # The preceding feature in this batch has already inserted parts.
            session.execute(text("SET LOCAL statement_timeout = '50ms'"))
            session.execute(text("SELECT pg_sleep(0.15)"))
        return original_project(session, feature_id, tolerance)

    with patch.object(display_builder, "_simplified", statement_timeout):
        try:
            build_environmental_display(LAYER, VERSION, batch_size=3)
        except DBAPIError as exc:
            assert getattr(exc.orig, "sqlstate", None) == "57014"
        else:
            raise AssertionError("statement timeout became a permanent feature verdict")
    assert _checkpoint_snapshot(_build_id(layer_id)) == checkpoint_before
    assert _canonical_hash(layer_id) == original_hash

    def system_failure(session, feature_id, tolerance):
        if feature_id == timeout_feature_id:
            session.execute(text("""
                DO $$ BEGIN
                    RAISE EXCEPTION 'synthetic storage failure' USING ERRCODE = '58030';
                END $$
            """))
        return original_project(session, feature_id, tolerance)

    with patch.object(display_builder, "_simplified", system_failure):
        try:
            build_environmental_display(LAYER, VERSION, batch_size=3)
        except DBAPIError as exc:
            assert getattr(exc.orig, "sqlstate", None) == "58030"
        else:
            raise AssertionError("database system failure became a permanent feature verdict")
    assert _checkpoint_snapshot(_build_id(layer_id)) == checkpoint_before
    derivation_lock_probed = False

    def probe_derivation_lock(session, feature_id, tolerance):
        nonlocal derivation_lock_probed
        if not derivation_lock_probed:
            try:
                with SessionLocal.begin() as writer:
                    writer.execute(text("SET LOCAL lock_timeout = '100ms'"))
                    writer.execute(text("""
                        UPDATE environmental_features SET geometry = ST_Translate(geometry, 1, 0)
                        WHERE id = :id
                    """), {"id": feature_id})
                    writer.execute(text("""
                        UPDATE environmental_features SET geometry = ST_Translate(geometry, -1, 0)
                        WHERE id = :id
                    """), {"id": feature_id})
            except DBAPIError as exc:
                assert getattr(exc.orig, "sqlstate", None) == "55P03"
                derivation_lock_probed = True
            else:
                raise AssertionError("writer could edit/restore between hash and derivation")
        return original_project(session, feature_id, tolerance)

    with patch.object(display_builder, "_simplified", probe_derivation_lock):
        first = build_environmental_display(LAYER, VERSION, batch_size=3)
    assert derivation_lock_probed
    assert first["display_status"] == "validated" and not first["publicly_active"]
    assert first["coverage_status"] == "unknown"
    assert all(band["status"] == "validated" for band in first["bands"])
    build_id = _build_id(layer_id)
    first_part_hash = _part_hash(build_id)
    replay = build_environmental_display(LAYER, VERSION, batch_size=7)
    assert replay["replayed"] and replay["display_version"] == first["display_version"]
    assert _part_hash(build_id) == first_part_hash
    with SessionLocal() as session:
        topology_result_id = session.scalar(text("""
            SELECT id FROM environmental_display_feature_results
            WHERE build_id = :id AND band_key = 'z08_10' AND source_feature_id = 'hole'
        """), {"id": build_id})
    for field in ("source_holes", "display_holes", "source_components", "display_components"):
        with SessionLocal.begin() as session:
            session.execute(text(f"""
                UPDATE environmental_display_feature_results SET {field} = {field} + 1
                WHERE id = :id
            """), {"id": topology_result_id})
        try:
            try:
                build_environmental_display(LAYER, VERSION)
            except DisplayBuildError as exc:
                assert str(exc) == "checkpoint_output_digest_mismatch"
            else:
                raise AssertionError("topology metadata tamper passed replay")
        finally:
            with SessionLocal.begin() as session:
                session.execute(text(f"""
                    UPDATE environmental_display_feature_results SET {field} = {field} - 1
                    WHERE id = :id
                """), {"id": topology_result_id})
    assert build_environmental_display(LAYER, VERSION)["replayed"]
    with SessionLocal.begin() as session:
        unmanaged_probe_id = session.scalar(text("""
            INSERT INTO environmental_features
                (environmental_layer_id, source_feature_id, attributes_json,
                 import_managed, import_fingerprint, geometry)
            SELECT environmental_layer_id, 'unmanaged-fence-probe', attributes_json,
                   false, import_fingerprint, geometry
            FROM environmental_features WHERE id = :id RETURNING id
        """), {"id": metadata[0]["id"]})
    original_snapshot = display_builder._source_snapshot
    final_lock_probes = set()

    def probe_final_lock(session, layer, *, lock_inputs=False):
        snapshot = original_snapshot(session, layer, lock_inputs=lock_inputs)
        if lock_inputs and layer.id == layer_id and not final_lock_probes:
            probes = (
                ("geometry", metadata[0]["id"], "geometry = ST_Translate(geometry, 1, 0)"),
                ("managed_flag", unmanaged_probe_id, "import_managed = true"),
            )
            for name, feature_id, assignment in probes:
                try:
                    with SessionLocal.begin() as writer:
                        writer.execute(text("SET LOCAL lock_timeout = '100ms'"))
                        writer.execute(text(f"""
                            UPDATE environmental_features SET {assignment} WHERE id = :id
                        """), {"id": feature_id})
                except DBAPIError as exc:
                    assert getattr(exc.orig, "sqlstate", None) == "55P03"
                    final_lock_probes.add(name)
                else:
                    raise AssertionError("noncooperating writer bypassed final snapshot locks")
        return snapshot

    try:
        with patch.object(display_builder, "_source_snapshot", probe_final_lock):
            assert build_environmental_display(LAYER, VERSION)["replayed"]
        assert final_lock_probes == {"geometry", "managed_flag"}
    finally:
        with SessionLocal.begin() as session:
            session.execute(text("DELETE FROM environmental_features WHERE id = :id"), {
                "id": unmanaged_probe_id,
            })
    # A coherent edit to geometry and its row SHA must still be detected by
    # the independently stored per-feature output digest on replay.
    with SessionLocal.begin() as session:
        part_id, original_ewkb, original_part_sha = session.execute(text("""
            SELECT id, ST_AsEWKB(geometry), geometry_sha256
            FROM environmental_display_parts WHERE build_id = :id
            ORDER BY id LIMIT 1
        """), {"id": build_id}).one()
        changed = session.scalar(text("""
            UPDATE environmental_display_parts
            SET geometry = ST_Translate(geometry, 1, 0)
            WHERE id = :id RETURNING ST_AsEWKB(geometry)
        """), {"id": part_id})
        session.execute(text("""
            UPDATE environmental_display_parts SET geometry_sha256 = :sha WHERE id = :id
        """), {"id": part_id, "sha": hashlib.sha256(bytes(changed)).hexdigest()})
    try:
        try:
            build_environmental_display(LAYER, VERSION)
        except DisplayBuildError as exc:
            assert str(exc) == "checkpoint_output_digest_mismatch"
        else:
            raise AssertionError("coherent part tamper passed replay validation")
    finally:
        with SessionLocal.begin() as session:
            session.execute(text("""
                UPDATE environmental_display_parts
                SET geometry = ST_GeomFromEWKB(:ewkb), geometry_sha256 = :sha
                WHERE id = :id
            """), {"id": part_id, "ewkb": bytes(original_ewkb), "sha": original_part_sha})
    assert build_environmental_display(LAYER, VERSION)["replayed"]
    _visual_samples(build_id, output)
    with SessionLocal.begin() as session:
        part_source_id = session.scalar(text("""
            UPDATE environmental_display_parts SET source_feature_id = 'wrong-source'
            WHERE id = :id RETURNING source_feature_id
        """), {"id": part_id})
        assert part_source_id == "wrong-source"
    try:
        try:
            build_environmental_display(LAYER, VERSION)
        except DisplayBuildError as exc:
            assert str(exc) == "checkpoint_part_digest_or_geometry_mismatch"
        else:
            raise AssertionError("changed part lineage passed replay validation")
    finally:
        with SessionLocal.begin() as session:
            session.execute(text("""
                UPDATE environmental_display_parts p SET source_feature_id = f.source_feature_id
                FROM environmental_features f
                WHERE p.id = :id AND f.id = p.environmental_feature_id
            """), {"id": part_id})
    # Exercise the current-size transfer guard with a small deterministic
    # ceiling rather than allocating a 32 MiB tamper fixture. Fingerprints are
    # unchanged deliberately, so the existing version's replay must catch it.
    with SessionLocal.begin() as session:
        feature_id, canonical_ewkb = session.execute(text("""
            SELECT id, ST_AsEWKB(geometry) FROM environmental_features
            WHERE environmental_layer_id = :id AND source_feature_id = 'hole'
        """), {"id": layer_id}).one()
        assert len(bytes(canonical_ewkb)) < 512
        enlarged_bytes = session.scalar(text("""
            UPDATE environmental_features SET geometry = ST_Segmentize(geometry, 0.0001)
            WHERE id = :id RETURNING octet_length(ST_AsEWKB(geometry))
        """), {"id": feature_id})
        assert enlarged_bytes > 512
    try:
        with patch.object(display_builder, "MAX_INPUT_BYTES", 512):
            try:
                build_environmental_display(LAYER, VERSION)
            except DisplayBuildError as exc:
                assert str(exc) == "canonical_snapshot_input_oversized"
            else:
                raise AssertionError("enlarged canonical input passed replay transfer guard")
    finally:
        with SessionLocal.begin() as session:
            session.execute(text("""
                UPDATE environmental_features SET geometry = ST_GeomFromEWKB(:ewkb)
                WHERE id = :id
            """), {"id": feature_id, "ewkb": bytes(canonical_ewkb)})
    assert build_environmental_display(LAYER, VERSION)["replayed"]
    assert _canonical_hash(layer_id) == original_hash
    assert _screening(layer_id) == original_screening

    # A geometry-only edit to an unprocessed row must change identity even
    # when a privileged writer leaves the P03 fingerprint unchanged.
    mutation_layer = "p04a_unprocessed_mutation"
    mutation_version = "9" * 64
    mutation_id = _seed_layer(mutation_layer, mutation_version, fixture)
    try:
        build_environmental_display(
            mutation_layer, mutation_version, batch_size=2, fail_after_batches=1,
        )
    except RuntimeError as exc:
        assert str(exc) == "injected_after_display_checkpoint"
    mutation_build_id = _build_id(mutation_id)
    mutation_checkpoint = _checkpoint_snapshot(mutation_build_id)
    with SessionLocal.begin() as session:
        unprocessed_id, unprocessed_ewkb = session.execute(text("""
            SELECT id, ST_AsEWKB(geometry) FROM environmental_features
            WHERE environmental_layer_id = :id ORDER BY id OFFSET 2 LIMIT 1
        """), {"id": mutation_id}).one()
        original_mutation_version = session.scalar(text("""
            SELECT display_version FROM environmental_display_builds WHERE id = :id
        """), {"id": mutation_build_id})
        session.execute(text("""
            UPDATE environmental_features SET geometry = ST_Translate(geometry, 0.001, 0)
            WHERE id = :id
        """), {"id": unprocessed_id})
    try:
        try:
            build_environmental_display(
                mutation_layer, mutation_version, batch_size=2, fail_after_batches=1,
            )
        except RuntimeError as exc:
            assert str(exc) == "injected_after_display_checkpoint"
        with SessionLocal() as session:
            versions = session.scalars(text("""
                SELECT display_version FROM environmental_display_builds
                WHERE environmental_layer_id = :id
            """), {"id": mutation_id}).all()
        assert len(versions) == 2 and len(set(versions)) == 2
        assert original_mutation_version in versions
        assert _checkpoint_snapshot(mutation_build_id) == mutation_checkpoint
    finally:
        with SessionLocal.begin() as session:
            session.execute(text("""
                UPDATE environmental_features SET geometry = ST_GeomFromEWKB(:ewkb)
                WHERE id = :id
            """), {"id": unprocessed_id, "ewkb": bytes(unprocessed_ewkb)})
    mutation_resume = build_environmental_display(mutation_layer, mutation_version)
    assert mutation_resume["display_version"] == original_mutation_version

    inflight_layer = "p04a_inflight_mutation"
    inflight_version = "8" * 64
    inflight_id = _seed_layer(inflight_layer, inflight_version, fixture)
    with SessionLocal() as session:
        inflight_feature_id, inflight_ewkb = session.execute(text("""
            SELECT id, ST_AsEWKB(geometry) FROM environmental_features
            WHERE environmental_layer_id = :id ORDER BY id OFFSET 2 LIMIT 1
        """), {"id": inflight_id}).one()

    def mutate_after_checkpoint(batch):
        if batch == 1:
            # Separate session deliberately bypasses the importer advisory lock.
            with SessionLocal.begin() as writer:
                writer.execute(text("""
                    UPDATE environmental_features SET geometry = ST_Translate(geometry, 0.001, 0)
                    WHERE id = :id
                """), {"id": inflight_feature_id})

    try:
        try:
            build_environmental_display(
                inflight_layer, inflight_version, batch_size=2,
                after_checkpoint=mutate_after_checkpoint,
            )
        except DisplayBuildError as exc:
            assert str(exc) == "source_snapshot_changed_during_build"
        else:
            raise AssertionError("inflight canonical mutation produced a validated build")
        with SessionLocal() as session:
            assert session.scalar(text("""
                SELECT status FROM environmental_display_builds WHERE environmental_layer_id = :id
            """), {"id": inflight_id}) != "validated"
    finally:
        with SessionLocal.begin() as session:
            session.execute(text("""
                UPDATE environmental_features SET geometry = ST_GeomFromEWKB(:ewkb)
                WHERE id = :id
            """), {"id": inflight_feature_id, "ewkb": bytes(inflight_ewkb)})
    with SessionLocal() as session:
        hole = session.execute(text("""
            SELECT r.source_holes, r.display_holes FROM environmental_display_feature_results r
            WHERE r.build_id = :id AND r.band_key = 'z17_18' AND r.source_feature_id = 'hole'
        """), {"id": build_id}).one()
        multipart = session.execute(text("""
            SELECT r.source_components, r.display_components
            FROM environmental_display_feature_results r
            WHERE r.build_id = :id AND r.band_key = 'z17_18'
              AND r.source_feature_id = 'multipart'
        """), {"id": build_id}).one()
        dense_parts = session.scalar(text("""
            SELECT count(*) FROM environmental_display_parts
            WHERE build_id = :id AND band_key = 'z17_18' AND source_feature_id = 'dense'
        """), {"id": build_id})
        maximum_vertices = session.scalar(text("""
            SELECT max(ST_NPoints(geometry)) FROM environmental_display_parts
            WHERE build_id = :id
        """), {"id": build_id})
        assert hole == (1, 1) and multipart == (2, 2)
        assert dense_parts > 1 and maximum_vertices <= 256
        plan_query = """
            EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) SELECT id FROM environmental_display_parts
            WHERE build_id = :id AND band_key = 'z17_18'
              AND geometry && ST_MakeEnvelope(-96e5, 40e5, -95e5, 41e5, 3857)
        """
        default_plan = session.execute(text(plan_query), {"id": build_id}).scalar()
        session.execute(text("SET LOCAL enable_seqscan = off"))
        forced_plan = session.execute(text("""
            EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) SELECT id FROM environmental_display_parts
            WHERE geometry && ST_MakeEnvelope(-96e5, 40e5, -95e5, 41e5, 3857)
        """)).scalar()
        assert "ix_environmental_display_parts_geometry" in json.dumps(forced_plan)
        catalog_after = session.scalar(text("""
            SELECT payload_json::text FROM processed_collection_items
            WHERE collection_name = 'map_layer_catalog' AND item_id = 'latest'
        """))
        assert catalog_after == catalog_before

    # An in-domain source with a deliberate SQL error for one feature proves a
    # savepoint rollback leaves the outer transaction able to store the next row.
    failure_layer = "p04a_savepoint"
    failure_version = "b" * 64
    failure_id = _seed_layer(failure_layer, failure_version, fixture[:2])
    with SessionLocal.begin() as session:
        session.execute(text("""
            UPDATE environmental_layers
            SET import_status = 'failed', coverage_status = 'partial',
                expected_count = 3, seen_count = 3, rejected_count = 1
            WHERE id = :id
        """), {"id": failure_id})
    with SessionLocal() as session:
        first_id = session.scalar(text("""
            SELECT min(id) FROM environmental_features WHERE environmental_layer_id = :id
        """), {"id": failure_id})
    original_simplified = display_builder._simplified

    def one_sql_failure(session, feature_id, tolerance):
        if feature_id == first_id:
            session.execute(text("SELECT 1/0"))
        return original_simplified(session, feature_id, tolerance)

    with patch.object(display_builder, "_simplified", one_sql_failure):
        failed = build_environmental_display(failure_layer, failure_version, batch_size=2)
    assert failed["display_status"] == "failed" and not failed["publicly_active"]
    assert failed["import_status"] == "failed" and failed["coverage_status"] == "partial"
    assert failed["source_counts"] == {
        "expected": 3, "seen": 3, "accepted": 2, "rejected": 1,
    }
    with SessionLocal() as session:
        statuses = [tuple(row) for row in session.execute(text("""
            SELECT source_feature_id, status FROM environmental_display_feature_results
            WHERE build_id = :id AND band_key = 'z17_18' ORDER BY source_feature_id
        """), {"id": _build_id(failure_id)}).all()]
    assert statuses == [("hole", "failed"), ("multipart", "built")]

    partial_id = _seed_layer("p04a_partial_import", "d" * 64, fixture[:1])
    with SessionLocal.begin() as session:
        session.execute(text("""
            UPDATE environmental_layers
            SET import_status = 'failed', coverage_status = 'partial',
                expected_count = 2, seen_count = 2, rejected_count = 1
            WHERE id = :id
        """), {"id": partial_id})
    partial = build_environmental_display("p04a_partial_import", "d" * 64)
    assert partial["display_status"] == "validated"
    assert partial["import_status"] == "failed" and partial["coverage_status"] == "partial"
    assert partial["source_counts"] == {
        "expected": 2, "seen": 2, "accepted": 1, "rejected": 1,
    }
    assert not partial["publicly_active"]
    # A same-data-version P03 resume changes the source snapshot. Its full
    # derivative must get a new identity; the partial shadow build stays intact.
    resumed_source_id, resumed_geometry = fixture[1]
    with SessionLocal.begin() as session:
        session.execute(text("""
            INSERT INTO environmental_features
                (environmental_layer_id, source_feature_id, attributes_json,
                 import_managed, import_fingerprint, geometry)
            VALUES (:layer_id, :source_id, CAST('{}' AS json), true,
                    :fingerprint, ST_GeomFromGeoJSON(:geometry))
        """), {
            "layer_id": partial_id, "source_id": resumed_source_id,
            "fingerprint": _digest([resumed_source_id, resumed_geometry]),
            "geometry": json.dumps(resumed_geometry),
        })
        session.execute(text("""
            UPDATE environmental_layers
            SET import_status = 'validated', coverage_status = 'unknown',
                accepted_count = 2, rejected_count = 0, import_checkpoint = 2
            WHERE id = :id
        """), {"id": partial_id})
    resumed = build_environmental_display("p04a_partial_import", "d" * 64)
    assert resumed["display_status"] == "validated"
    assert resumed["display_version"] != partial["display_version"]
    assert resumed["source_snapshot_sha256"] != partial["source_snapshot_sha256"]
    assert not resumed["publicly_active"]
    with SessionLocal() as session:
        old = session.execute(text("""
            SELECT status, summary_json FROM environmental_display_builds
            WHERE environmental_layer_id = :id AND display_version = :version
        """), {"id": partial_id, "version": partial["display_version"]}).one()
        assert old.status == "validated" and old.summary_json["canonical_feature_count"] == 1

    out_of_domain = "p04a_projection_failure"
    bad_id = _seed_layer(out_of_domain, "c" * 64, [(
        "latitude-86", {"type": "Polygon", "coordinates": [[
            [-86.7, 86.0], [-86.6, 86.0], [-86.6, 86.1],
            [-86.7, 86.1], [-86.7, 86.0],
        ]]},
    )])
    bad_hash = _canonical_hash(bad_id)
    bad = build_environmental_display(out_of_domain, "c" * 64)
    assert bad["display_status"] == "failed" and all(
        band["invalid"] == 1 for band in bad["bands"]
    )
    assert _canonical_hash(bad_id) == bad_hash
    bad_build_id = _build_id(bad_id)
    failed_checkpoint = _checkpoint_snapshot(bad_build_id)
    with SessionLocal.begin() as session:
        session.execute(text("""
            UPDATE environmental_display_builds SET status = 'validated' WHERE id = :id
        """), {"id": bad_build_id})
        session.execute(text("""
            UPDATE environmental_display_bands SET status = 'validated' WHERE build_id = :id
        """), {"id": bad_build_id})
    try:
        try:
            build_environmental_display(out_of_domain, "c" * 64)
        except DisplayBuildError as exc:
            assert str(exc) == "validated_band_contains_failed_results"
        else:
            raise AssertionError("status-only promotion concealed failed feature results")
    finally:
        with SessionLocal.begin() as session:
            session.execute(text("""
                UPDATE environmental_display_builds SET status = 'failed' WHERE id = :id
            """), {"id": bad_build_id})
            session.execute(text("""
                UPDATE environmental_display_bands SET status = 'failed' WHERE build_id = :id
            """), {"id": bad_build_id})
    assert _checkpoint_snapshot(bad_build_id) == failed_checkpoint
    with SessionLocal() as session:
        diagnostic_band_id, original_diagnostics = session.execute(text("""
            SELECT id, diagnostics_json FROM environmental_display_bands
            WHERE build_id = :id ORDER BY band_key LIMIT 1
        """), {"id": bad_build_id}).one()
    corrupt_diagnostics = (
        {"samples": original_diagnostics["samples"]},  # removed failure count
        {**original_diagnostics, "samples": [
            {"source_feature_id": "unrelated-source", "code": "invented-code"},
        ]},
    )
    for diagnostic in corrupt_diagnostics:
        with SessionLocal.begin() as session:
            session.execute(text("""
                UPDATE environmental_display_bands
                SET diagnostics_json = CAST(:diagnostic AS json) WHERE id = :id
            """), {"id": diagnostic_band_id, "diagnostic": json.dumps(diagnostic)})
        try:
            try:
                build_environmental_display(out_of_domain, "c" * 64)
            except DisplayBuildError as exc:
                assert str(exc) == "checkpoint_diagnostics_mismatch"
            else:
                raise AssertionError("diagnostic count/sample tamper passed replay")
        finally:
            with SessionLocal.begin() as session:
                session.execute(text("""
                    UPDATE environmental_display_bands
                    SET diagnostics_json = CAST(:diagnostic AS json) WHERE id = :id
                """), {"id": diagnostic_band_id,
                       "diagnostic": json.dumps(original_diagnostics)})
    selective_plan = _selective_plan(build_id)
    # Simulate a database copy that allocates feature IDs in the reverse order.
    # Rename the first fixture layer only after all of its replay checks; its
    # retained display bytes are untouched and no production writer is involved.
    with SessionLocal.begin() as session:
        session.execute(text("""
            UPDATE environmental_layers SET layer_key = :archived WHERE id = :id
        """), {"archived": LAYER + "_original", "id": layer_id})
    replica_id = _seed_layer(LAYER, VERSION, list(reversed(fixture)))
    replica = build_environmental_display(LAYER, VERSION, batch_size=1)
    assert replica["display_version"] == first["display_version"]
    assert replica["source_snapshot_sha256"] == first["source_snapshot_sha256"]
    assert [band["parts_sha256"] for band in replica["bands"]] == [
        band["parts_sha256"] for band in first["bands"]
    ]
    assert _part_hash(_build_id(replica_id)) == first_part_hash
    assert build_environmental_display(LAYER, VERSION)["replayed"]
    result = {
        "fixture_sha256": _digest(fixture),
        "original_geometry_sha256": original_hash,
        "screening_hits": original_screening,
        "display_version": first["display_version"],
        "config_sha256": first["config_sha256"],
        "part_sha256": first_part_hash,
        "reverse_insertion_order_checksums_match": True,
        "metadata_only_input_batches": True,
        "enlarged_canonical_replay_refused": True,
        "statement_timeout_preserves_committed_checkpoint": True,
        "system_failure_preserves_committed_checkpoint": True,
        "topology_metadata_tamper_refused": True,
        "inflight_canonical_mutation_prevents_validation": True,
        "final_snapshot_blocks_noncooperating_writer": True,
        "final_snapshot_blocks_unmanaged_to_managed_toggle": True,
        "status_only_promotion_of_failed_build_refused": True,
        "diagnostic_count_and_sample_tamper_refused": True,
        "batch_lock_blocks_hash_to_derivation_edit_restore": True,
        "unprocessed_geometry_mutation_changes_identity": True,
        "postgis_execution_version": first["postgis_execution_version"],
        "bands": first["bands"],
        "hole_counts": list(hole), "multipart_components": list(multipart),
        "dense_parts": dense_parts, "maximum_part_vertices": maximum_vertices,
        "default_plan": default_plan, "forced_plan": forced_plan,
        "selective_default_plan": selective_plan,
        "plan_background_parts": 6000,
        "visual_sample": "fill-only-bands.svg",
        "savepoint_statuses": statuses,
        "partial_import_display_status": partial["display_status"],
        "resumed_display_version": resumed["display_version"],
        "projection_failed_bands": len(bad["bands"]),
        "publicly_active": False,
    }
    (output / "results.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    result = run(arguments.output)
    print(json.dumps({"status": "passed", "result_sha256": _digest(result)}, sort_keys=True))
