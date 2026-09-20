#!/usr/bin/env node
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";

function parseArgs(argv) {
  const options = { fixture: null, manifest: null };
  for (let index = 0; index < argv.length; index += 1) {
    const argument = argv[index];
    if (argument === "--fixture" || argument === "--manifest") {
      const value = argv[++index];
      if (!value) throw new Error(`${argument} requires a value`);
      options[argument.slice(2)] = resolve(value);
    } else {
      throw new Error(`Unknown option ${argument}`);
    }
  }
  if (!options.fixture) throw new Error("--fixture is required");
  options.manifest ??= `${options.fixture}.manifest.json`;
  return options;
}

function signedArea(ring) {
  let area = 0;
  for (let index = 1; index < ring.length; index += 1) {
    area += ring[index - 1][0] * ring[index][1] - ring[index][0] * ring[index - 1][1];
  }
  return area / 2;
}

function orientation(a, b, c) {
  const value = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]);
  if (Math.abs(value) < 1e-12) return 0;
  return value > 0 ? 1 : -1;
}

function onSegment(a, b, point) {
  return point[0] >= Math.min(a[0], b[0]) - 1e-12
    && point[0] <= Math.max(a[0], b[0]) + 1e-12
    && point[1] >= Math.min(a[1], b[1]) - 1e-12
    && point[1] <= Math.max(a[1], b[1]) + 1e-12;
}

function segmentsIntersect(a, b, c, d) {
  const first = orientation(a, b, c);
  const second = orientation(a, b, d);
  const third = orientation(c, d, a);
  const fourth = orientation(c, d, b);
  if (first !== second && third !== fourth) return true;
  return (first === 0 && onSegment(a, b, c))
    || (second === 0 && onSegment(a, b, d))
    || (third === 0 && onSegment(c, d, a))
    || (fourth === 0 && onSegment(c, d, b));
}

function validRing(ring, checkIntersections = false) {
  if (!Array.isArray(ring) || ring.length < 4) return false;
  if (JSON.stringify(ring[0]) !== JSON.stringify(ring.at(-1))) return false;
  if (Math.abs(signedArea(ring)) < 1e-12) return false;
  if (ring.some((point) => !Array.isArray(point) || point.length < 2 || point.some((value) => !Number.isFinite(value)))) return false;
  if (checkIntersections) {
    for (let first = 0; first < ring.length - 1; first += 1) {
      for (let second = first + 1; second < ring.length - 1; second += 1) {
        if (second === first + 1 || (first === 0 && second === ring.length - 2)) continue;
        if (segmentsIntersect(ring[first], ring[first + 1], ring[second], ring[second + 1])) return false;
      }
    }
  }
  return true;
}

function probePointInRing(point, ring) {
  let inside = false;
  for (let index = 0, previous = ring.length - 1; index < ring.length; previous = index++) {
    const [x, y] = ring[index];
    const [previousX, previousY] = ring[previous];
    if (((y > point[1]) !== (previousY > point[1]))
      && point[0] < ((previousX - x) * (point[1] - y)) / (previousY - y) + x) {
      inside = !inside;
    }
  }
  return inside;
}

function validPolygon(rings, checkIntersections = false) {
  if (!Array.isArray(rings) || !validRing(rings[0], checkIntersections)) return false;
  for (let index = 1; index < rings.length; index += 1) {
    if (!validRing(rings[index], checkIntersections) || !pointInRing(rings[index][0], rings[0])) return false;
    if (checkIntersections) {
      for (let prior = 1; prior < index; prior += 1) {
        if (segmentsIntersect(rings[index][0], rings[index][1], rings[prior][0], rings[prior][1])) return false;
      }
    }
  }
  return true;
}

function validGeometry(geometry, checkIntersections = false) {
  if (!geometry || typeof geometry !== "object") return false;
  if (geometry.type === "Point") return Array.isArray(geometry.coordinates) && geometry.coordinates.length >= 2 && geometry.coordinates.every(Number.isFinite);
  if (geometry.type === "LineString") return Array.isArray(geometry.coordinates) && geometry.coordinates.length >= 2 && geometry.coordinates.every((point) => Array.isArray(point) && point.length >= 2 && point.every(Number.isFinite));
  if (geometry.type === "Polygon") return validPolygon(geometry.coordinates, checkIntersections);
  if (geometry.type === "MultiPolygon") return Array.isArray(geometry.coordinates) && geometry.coordinates.length > 0 && geometry.coordinates.every((polygon) => validPolygon(polygon, checkIntersections));
  return false;
}

function pointInRing(point, ring) {
  let inside = false;
  for (let index = 0, previous = ring.length - 1; index < ring.length; previous = index++) {
    const [x, y] = ring[index];
    const [previousX, previousY] = ring[previous];
    if (((y > point[1]) !== (previousY > point[1]))
      && point[0] < ((previousX - x) * (point[1] - y)) / (previousY - y) + x) inside = !inside;
  }
  return inside;
}

function pointInPolygon(point, geometry) {
  const polygons = geometry.type === "Polygon" ? [geometry.coordinates] : geometry.coordinates;
  return polygons.some((rings) => probePointInRing(point, rings[0]) && rings.slice(1).every((ring) => !probePointInRing(point, ring)));
}

function slippyWestEdge(zoom, tileX) {
  return (tileX / 2 ** zoom) * 360 - 180;
}

function features(fixture) {
  return fixture.environmental_overlays.flatMap((overlay) => overlay.features.features);
}

const options = parseArgs(process.argv.slice(2));
const fixtureText = await readFile(options.fixture, "utf8");
const fixture = JSON.parse(fixtureText);
const manifest = JSON.parse(await readFile(options.manifest, "utf8"));
const environmentalFeatures = features(fixture);
const allGeometries = [
  ...fixture.development_records.map((record) => record.geometry),
  ...environmentalFeatures.map((feature) => feature.geometry)
];
if (allGeometries.some((geometry) => !validGeometry(geometry))) throw new Error("valid fixture geometry failed structural validation");
if (environmentalFeatures.some((feature) => feature.properties?.fixture_feature_id !== feature.id)) {
  throw new Error("environmental feature stable id property does not match its GeoJSON id");
}
const invalidDiagnostic = fixture.fixture_diagnostics?.quarantined_invalid?.[0]?.geometry;
if (!invalidDiagnostic || validGeometry(invalidDiagnostic, true)) throw new Error("quarantined invalid diagnostic was not rejected");
if (fixture.fixture_diagnostics.unsupported_unlocated_records.some((diagnostic) => fixture.development_records.some((record) => record.public_id === diagnostic.id))) {
  throw new Error("unsupported unlocated diagnostic leaked into published records");
}
const probe = manifest.overlay_probes?.[0];
const probeFeature = environmentalFeatures.find((feature) => feature.id === probe?.feature_id);
if (!probe || !probeFeature || probe.overlay_id !== fixture.environmental_overlays[0].id || !pointInPolygon(probe.coordinate, probeFeature.geometry)) {
  throw new Error("manifest overlay probe is not inside its published geometry");
}
const tileDiagnostic = fixture.fixture_diagnostics.touching_tile_boundaries?.[0];
const expectedWest = slippyWestEdge(tileDiagnostic.zoom, tileDiagnostic.tile_x);
if (!tileDiagnostic?.geometry || Math.abs(tileDiagnostic.coordinate[0] - expectedWest) > 1e-12
  || !tileDiagnostic.geometry.coordinates[0].some(([longitude]) => Math.abs(longitude - expectedWest) < 1e-12)) {
  throw new Error("tile-boundary diagnostic does not touch its declared slippy tile edge");
}
const tileFeature = environmentalFeatures.find((feature) => feature.id === tileDiagnostic.published_feature_id);
if (!tileFeature || tileFeature.properties.geometry_case !== "tile-boundary-touch"
  || !tileFeature.geometry.coordinates[0].some(([longitude]) => Math.abs(longitude - expectedWest) < 1e-12)) {
  throw new Error("published fixture does not contain the declared valid tile-boundary feature");
}
const sourceCoverage = fixture.fixture_metadata?.source_coverage;
if (!sourceCoverage?.synthetic || !sourceCoverage.disclaimer || sourceCoverage.sources?.length !== 2
  || !sourceCoverage.sources.some((source) => source.status === "complete")
  || !sourceCoverage.sources.some((source) => source.status === "partial")) {
  throw new Error("fixture source coverage metadata must explicitly include synthetic complete and partial sources");
}
const sha256 = createHash("sha256").update(fixtureText).digest("hex");
if (manifest.sha256 !== sha256) throw new Error(`fixture checksum mismatch: ${sha256} != ${manifest.sha256}`);
if (manifest.development_records !== fixture.development_records.length || manifest.environmental_features !== environmentalFeatures.length) {
  throw new Error("fixture manifest counts do not match payload");
}
const geometryCases = [...new Set(environmentalFeatures.map((feature) => feature.properties.geometry_case))].sort();
if (JSON.stringify(manifest.geometry_cases) !== JSON.stringify(geometryCases)) throw new Error("fixture manifest geometry cases do not match payload");
if (!pointInPolygon(fixture.development_records[0].centroid, fixture.development_records[0].geometry)) {
  throw new Error("first development centroid is not inside its published geometry");
}
const coordinatePairs = allGeometries.reduce((total, geometry) => {
  const count = (value) => Array.isArray(value) && value.length >= 2 && value.every((part) => typeof part === "number")
    ? 1
    : Array.isArray(value) ? value.reduce((sum, child) => sum + count(child), 0) : 0;
  return total + count(geometry.coordinates);
}, 0);
if (manifest.environmental_coordinate_pairs !== environmentalFeatures.reduce((total, feature) => {
  const count = (value) => Array.isArray(value) && value.length >= 2 && value.every((part) => typeof part === "number")
    ? 1
    : Array.isArray(value) ? value.reduce((sum, child) => sum + count(child), 0) : 0;
  return total + count(feature.geometry.coordinates);
}, 0)) throw new Error("environmental coordinate-pair count does not match payload");
if (manifest.expected.first_development.public_id !== fixture.development_records[0].public_id
  || JSON.stringify(manifest.expected.first_development.centroid) !== JSON.stringify(fixture.development_records[0].centroid)) {
  throw new Error("manifest first record identity or centroid mismatch");
}
console.log(JSON.stringify({
  fixture: options.fixture,
  profile: manifest.profile,
  sha256,
  development_records: fixture.development_records.length,
  environmental_features: environmentalFeatures.length,
  coordinate_pairs_including_developments: coordinatePairs,
  geometry_validation: "passed",
  published_tile_boundary_feature: tileFeature.id,
  source_coverage: sourceCoverage,
  quarantined_invalid_rejected: true,
  diagnostics: manifest.diagnostics
}, null, 2));
