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
  const cx = center?.[0] ?? -86.88 + (index % 80) * 0.0053;
  const cy = center?.[1] ?? 34.58 + (Math.floor(index / 80) % 52) * 0.0061;
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
  const baseX = -86.9 + (index % 60) * 0.007;
  const baseY = 34.6 + (Math.floor(index / 60) % 55) * 0.005;
  for (let point = 0; point < points; point += 1) {
    coordinates.push([
      Number((baseX + point * 0.00006).toFixed(6)),
      Number((baseY + Math.sin(point / 13) * 0.0008 + random() * 0.0002).toFixed(6))
    ]);
  }
  return { type: "LineString", coordinates };
}

function environmentalFeature(index, random, dense) {
  const geometry = index % 11 === 0 ? lineGeometry(index, random, dense) : polygonGeometry(index, random, dense);
  const geometryCase = geometry.type === "LineString"
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
      class: index % 3 === 0 ? "wetland" : index % 3 === 1 ? "floodplain" : "boundary",
      geometry_case: geometryCase
    }
  };
}

function developmentRecord(index, random, profile) {
  const x = -86.87 + (index % 80) * 0.0053;
  const y = 34.59 + (Math.floor(index / 80) % 50) * 0.006;
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
  return {
    development_records,
    environmental_overlays,
    source_health: { status: "healthy", sources: [], records: { fixture: developmentCount } }
  };
}

function stats(fixture, profile, seed, bytes, sha256) {
  const features = fixture.environmental_overlays.flatMap((overlay) => overlay.features.features);
  const coordinatePairsCount = features.reduce((total, feature) => total + coordinatePairs(feature.geometry.coordinates), 0);
  const geometryCases = [...new Set(features.map((feature) => feature.properties.geometry_case))].sort();
  return {
    profile,
    seed,
    development_records: fixture.development_records.length,
    environmental_features: features.length,
    environmental_coordinate_pairs: coordinatePairsCount,
    geometry_cases: geometryCases,
    bytes_utf8: bytes,
    sha256
  };
}

const options = parseArgs(process.argv.slice(2));
const fixture = createFixture(options.profile, options.seed);
const serialized = `${JSON.stringify(fixture)}\n`;
const bytes = Buffer.byteLength(serialized);
const sha256 = createHash("sha256").update(serialized).digest("hex");
await mkdir(dirname(options.output), { recursive: true });
await writeFile(options.output, serialized, "utf8");
const manifestPath = `${options.output}.manifest.json`;
await writeFile(manifestPath, `${JSON.stringify(stats(fixture, options.profile, options.seed, bytes, sha256), null, 2)}\n`, "utf8");
console.log(JSON.stringify({ fixture: options.output, manifest: manifestPath, ...stats(fixture, options.profile, options.seed, bytes, sha256) }, null, 2));
