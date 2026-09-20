#!/usr/bin/env node
import { createHash } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";

const DEFAULT_SEED = 0x51a7c0de;

function parseArgs(argv) {
  const options = { profile: "A", seed: DEFAULT_SEED, output: null };
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === "--profile" || arg === "--seed" || arg === "--output") {
      const value = argv[++index];
      if (!value) throw new Error(`${arg} requires a value`);
      if (arg === "--profile") options.profile = value.toUpperCase();
      else if (arg === "--seed") options.seed = Number(value);
      else options.output = resolve(value);
    } else {
      throw new Error(`Unknown option ${arg}`);
    }
  }
  if (!new Set(["A", "B"]).has(options.profile)) throw new Error("--profile must be A or B");
  if (!Number.isSafeInteger(options.seed) || options.seed < 0) throw new Error("--seed must be a non-negative integer");
  if (!options.output) throw new Error("--output is required");
  return options;
}

function rng(seed) {
  let state = seed >>> 0;
  return () => {
    state = (state * 1664525 + 1013904223) >>> 0;
    return state / 0x100000000;
  };
}

function coordinatePairs(value) {
  if (!Array.isArray(value)) return 0;
  if (value.length >= 2 && value.every((part) => typeof part === "number")) return 1;
  return value.reduce((total, child) => total + coordinatePairs(child), 0);
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

function validateRing(ring, checkIntersections = false) {
  if (!Array.isArray(ring) || ring.length < 4) return false;
  if (JSON.stringify(ring[0]) !== JSON.stringify(ring.at(-1))) return false;
  if (Math.abs(signedArea(ring)) < 1e-12) return false;
  for (const coordinate of ring) {
    if (!Array.isArray(coordinate) || coordinate.length < 2 || coordinate.some((value) => !Number.isFinite(value))) {
      return false;
    }
  }
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

function pointInRing(point, ring) {
  let inside = false;
  for (let index = 0, previous = ring.length - 1; index < ring.length; previous = index++) {
    const [x, y] = ring[index];
    const [previousX, previousY] = ring[previous];
    const intersects = ((y > point[1]) !== (previousY > point[1]))
      && point[0] < ((previousX - x) * (point[1] - y)) / (previousY - y) + x;
    if (intersects) inside = !inside;
  }
  return inside;
}

function validatePolygonRings(rings, checkIntersections = false) {
  if (!Array.isArray(rings) || !validateRing(rings[0], checkIntersections)) return false;
  for (let index = 1; index < rings.length; index += 1) {
    if (!validateRing(rings[index], checkIntersections) || !pointInRing(rings[index][0], rings[0])) return false;
    if (checkIntersections) {
      for (let prior = 1; prior < index; prior += 1) {
        if (segmentsIntersect(rings[index][0], rings[index][1], rings[prior][0], rings[prior][1])) return false;
      }
    }
  }
  return true;
}

function validateGeometry(geometry, checkIntersections = false) {
  if (!geometry || typeof geometry !== "object") return false;
  if (geometry.type === "Point") {
    return Array.isArray(geometry.coordinates)
      && geometry.coordinates.length >= 2
      && geometry.coordinates.every((value) => Number.isFinite(value));
  }
  if (geometry.type === "LineString") {
    return Array.isArray(geometry.coordinates)
      && geometry.coordinates.length >= 2
      && geometry.coordinates.every((point) => Array.isArray(point) && point.length >= 2 && point.every((value) => Number.isFinite(value)));
  }
  if (geometry.type === "Polygon") return validatePolygonRings(geometry.coordinates, checkIntersections);
  if (geometry.type === "MultiPolygon") {
    return Array.isArray(geometry.coordinates)
      && geometry.coordinates.length > 0
      && geometry.coordinates.every((polygon) => validatePolygonRings(polygon, checkIntersections));
  }
  return false;
}

function polygonRing(cx, cy, radiusX, radiusY, points, random, phase = 0) {
  const ring = [];
  for (let index = 0; index < points; index += 1) {
    const angle = phase + (index / points) * Math.PI * 2;
    const wobble = 0.78 + random() * 0.42;
    ring.push([
      Number((cx + Math.cos(angle) * radiusX * wobble).toFixed(6)),
      Number((cy + Math.sin(angle) * radiusY * wobble).toFixed(6))
    ]);
  }
  ring.push(ring[0]);
  return ring;
}

function polygonGeometry(index, random, dense, center = null) {
  const cx = center?.[0] ?? -86.86 + (index % 80) * 0.0052;
  const cy = center?.[1] ?? 34.615 + (Math.floor(index / 80) % 52) * 0.0056;
  const points = dense ? 950 + (index % 5) * 40 : 24 + (index % 5) * 4;
  const outer = polygonRing(cx, cy, 0.0022, 0.0016, points, random, index * 0.17);
  const ringCount = index % 9 === 0 ? 2 : index % 4 === 0 ? 1 : 0;
  const holes = [];
  for (let hole = 0; hole < ringCount; hole += 1) {
    holes.push(polygonRing(cx + (hole === 0 ? -0.0007 : 0.0007), cy, 0.00022, 0.00016, Math.max(8, Math.floor(points / 18)), random, hole));
  }
  if (index % 7 === 0) {
    const second = polygonRing(cx + 0.0048, cy + 0.0023, 0.0014, 0.001, Math.max(16, Math.floor(points / 2)), random, 0.4);
    return { type: "MultiPolygon", coordinates: [[[...outer], ...holes], [second]] };
  }
  return { type: "Polygon", coordinates: [[...outer], ...holes] };
}

function lineGeometry(index, random, dense) {
  const points = dense ? 850 + (index % 7) * 30 : 18 + (index % 6) * 3;
  const coordinates = [];
  const baseX = -86.86 + (index % 60) * 0.0067;
  const baseY = 34.63 + (Math.floor(index / 60) % 55) * 0.0049;
  for (let point = 0; point < points; point += 1) {
    coordinates.push([
      Number((baseX + point * 0.00006).toFixed(6)),
      Number((baseY + Math.sin(point / 13) * 0.0008 + random() * 0.0002).toFixed(6))
    ]);
  }
  return { type: "LineString", coordinates };
}

function tileBoundaryGeometry() {
  const west = -86.748046875;
  return {
    type: "Polygon",
    coordinates: [[
      [west, 34.748],
      [west + 0.001, 34.748],
      [west + 0.001, 34.752],
      [west, 34.752],
      [west, 34.748]
    ]]
  };
}

function environmentalFeature(index, random, dense) {
  const geometry = index === 2
    ? tileBoundaryGeometry()
    : index % 11 === 0 ? lineGeometry(index, random, dense) : polygonGeometry(index, random, dense);
  const geometryCase = index === 2
    ? "tile-boundary-touch"
    : geometry.type === "LineString"
    ? "dense-line"
    : geometry.type === "MultiPolygon"
      ? "multipolygon"
      : geometry.coordinates.length > 1
        ? "holes"
        : "polygon";
  return {
    type: "Feature",
    id: `p01-environment-${index}`,
    geometry,
    properties: {
      source_feature_id: `p01-${index}`,
      fixture_feature_id: `p01-environment-${index}`,
      class: index % 3 === 0 ? "wetland" : index % 3 === 1 ? "floodplain" : "boundary",
      geometry_case: geometryCase,
      ...(index === 1 ? { fixture_probe_coordinate: [-86.8548, 34.615] } : {})
    }
  };
}

function developmentRecord(index, random, profile) {
  const x = index === 0 ? -86.66 : -86.86 + (index % 80) * 0.0052;
  const y = index === 0 ? 34.85 : 34.625 + (Math.floor(index / 80) % 50) * 0.0058;
  const geometry = index % 10 === 0
    ? polygonGeometry(index, random, false, [x, y])
    : { type: "Point", coordinates: [Number(x.toFixed(6)), Number(y.toFixed(6))] };
  const centroid = geometry.type === "Point" ? geometry.coordinates : [Number(x.toFixed(6)), Number(y.toFixed(6))];
  return {
    public_id: `p01-${profile.toLowerCase()}-development-${String(index).padStart(4, "0")}`,
    title: `P01 ${profile} development ${index}`,
    description: "Deterministic P01 performance fixture record.",
    development_type: index % 2 === 0 ? "subdivision" : "building_permit",
    status: index % 4 === 0 ? "preliminary" : "layout",
    source_status: "fixture",
    source_url: "https://example.test/p01",
    source_agency: "P01 deterministic fixture",
    date_discovered: "2026-09-20",
    date_last_checked: "2026-09-20",
    application_date: null,
    approval_date: null,
    permit_issue_date: null,
    review_status: "published",
    confidence_level: "high",
    geometry_source: "P01 generated geometry",
    geometry_confidence: "high",
    geometry,
    centroid,
    area_sq_m: null,
    address: null,
    parcel_ids: [],
    source_fields: { fixture: "p01", profile },
    proximity_flags: []
  };
}

function createFixture(profile, seed) {
  const random = rng(seed);
  const isLarge = profile === "B";
  const developmentCount = isLarge ? 1324 : 32;
  const overlayCount = isLarge ? 4000 : 16;
  const development_records = Array.from({ length: developmentCount }, (_, index) => developmentRecord(index, random, profile));
  const environmentalFeatures = Array.from({ length: overlayCount }, (_, index) => environmentalFeature(index, random, isLarge));
  const environmental_overlays = [{
    id: "wetlands",
    name: `P01 ${profile} rendered context`,
    category: "wetlands",
    source_url: "https://example.test/p01/context",
    attribution: "P01 deterministic fixture",
    caveat: "Synthetic performance geometry; not a planning source.",
    geom_type: "polygon",
    features: { type: "FeatureCollection", features: environmentalFeatures }
  }];
  const sourceCoverage = {
    synthetic: true,
    disclaimer: "Fixture coverage metadata is synthetic and does not claim completeness for any real source.",
    sources: [
      {
        id: "p01-synthetic-complete",
        status: "complete",
        scope_id: `p01-${profile.toLowerCase()}-complete-scope`,
        expected_features: overlayCount,
        fetched_features: overlayCount,
        note: "All generated features for this synthetic source are present."
      },
      {
        id: "p01-synthetic-partial",
        status: "partial",
        scope_id: `p01-${profile.toLowerCase()}-partial-scope`,
        expected_features: overlayCount + 8,
        fetched_features: overlayCount,
        note: "Eight synthetic source features are intentionally outside this fixture."
      }
    ]
  };
  const fixture_diagnostics = {
    quarantined_invalid: [{
      id: "p01-invalid-self-intersection",
      reason: "self-intersecting-ring",
      geometry: {
        type: "Polygon",
        coordinates: [[[0, 0], [1, 1], [0, 1], [1, 0], [0, 0]]]
      }
    }],
    touching_tile_boundaries: [{
      id: "p01-tile-boundary-touch",
      reason: "published polygon deliberately touches a real slippy-map tile west edge",
      boundary: "west",
      published_feature_id: "p01-environment-2",
      zoom: 12,
      tile_x: 1061,
      coordinate: [-86.748046875, 34.75],
      geometry: {
        type: "Polygon",
        coordinates: [[[-86.748046875, 34.748], [-86.747046875, 34.748], [-86.747046875, 34.752], [-86.748046875, 34.752], [-86.748046875, 34.748]]]
      }
    }],
    unsupported_unlocated_records: [{
      id: "p01-unlocated-diagnostic",
      reason: "published source record has no usable geometry or centroid; excluded from development_records"
    }]
  };
  return {
    development_records,
    environmental_overlays,
    source_health: {
      status: "healthy",
      sources: [],
      records: { fixture: developmentCount },
      fixture_coverage: sourceCoverage
    },
    fixture_metadata: { source_coverage: sourceCoverage },
    fixture_diagnostics
  };
}

function stats(fixture, profile, seed, bytes, sha256) {
  const features = fixture.environmental_overlays.flatMap((overlay) => overlay.features.features);
  const coordinatePairsCount = features.reduce((total, feature) => total + coordinatePairs(feature.geometry.coordinates), 0);
  const geometryCases = [...new Set(features.map((feature) => feature.properties.geometry_case))].sort();
  const first = fixture.development_records[0];
  const probeFeature = features.find((feature) => feature.id === "p01-environment-1");
  return {
    schema_version: 1,
    generator: {
      name: "p01-performance-fixture",
      version: 2,
      settings: { dense_polygon_points: "950-1110", development_grid: "80x17", overlay_grid: "80x52" }
    },
    profile,
    seed,
    development_records: fixture.development_records.length,
    environmental_features: features.length,
    environmental_coordinate_pairs: coordinatePairsCount,
    geometry_cases: geometryCases,
    source_coverage: fixture.fixture_metadata.source_coverage,
    expected: {
      first_development: { public_id: first.public_id, title: first.title, centroid: first.centroid },
      visible_geometry_cases: geometryCases,
      enabled_overlay_id: fixture.environmental_overlays[0].id
    },
    overlay_probes: [{
      overlay_id: fixture.environmental_overlays[0].id,
      overlay_name: fixture.environmental_overlays[0].name,
      feature_id: probeFeature.id,
      coordinate: probeFeature.properties.fixture_probe_coordinate
    }],
    diagnostics: {
      quarantined_invalid: fixture.fixture_diagnostics.quarantined_invalid.map(({ id, reason }) => ({ id, reason })),
      touching_tile_boundaries: fixture.fixture_diagnostics.touching_tile_boundaries.map(({ id, reason, boundary, published_feature_id, zoom, tile_x, coordinate }) => ({ id, reason, boundary, published_feature_id, zoom, tile_x, coordinate })),
      unsupported_unlocated_records: fixture.fixture_diagnostics.unsupported_unlocated_records.map(({ id, reason }) => ({ id, reason }))
    },
    bytes_utf8: bytes,
    sha256
  };
}

const options = parseArgs(process.argv.slice(2));
const fixture = createFixture(options.profile, options.seed);
for (const record of fixture.development_records) {
  if (!validateGeometry(record.geometry)) throw new Error(`generated development geometry is invalid: ${record.public_id}`);
}
for (const overlay of fixture.environmental_overlays) {
  for (const feature of overlay.features.features) {
    if (!validateGeometry(feature.geometry)) throw new Error(`generated environmental geometry is invalid: ${feature.id}`);
  }
}
if (validateGeometry(fixture.fixture_diagnostics.quarantined_invalid[0].geometry, true)) {
  throw new Error("quarantined invalid diagnostic unexpectedly passed geometry validation");
}
if (!validateGeometry(fixture.fixture_diagnostics.touching_tile_boundaries[0].geometry)) {
  throw new Error("tile-boundary diagnostic geometry unexpectedly failed validation");
}
const serialized = `${JSON.stringify(fixture)}\n`;
const bytes = Buffer.byteLength(serialized);
const sha256 = createHash("sha256").update(serialized).digest("hex");
await mkdir(dirname(options.output), { recursive: true });
await writeFile(options.output, serialized, "utf8");
const manifestPath = `${options.output}.manifest.json`;
await writeFile(manifestPath, `${JSON.stringify(stats(fixture, options.profile, options.seed, bytes, sha256), null, 2)}\n`, "utf8");
console.log(JSON.stringify({ fixture: options.output, manifest: manifestPath, ...stats(fixture, options.profile, options.seed, bytes, sha256) }, null, 2));
