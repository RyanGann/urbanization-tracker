import { createHash } from 'node:crypto';
import { readFile, realpath, writeFile } from 'node:fs/promises';
import { isAbsolute, join, relative, sep } from 'node:path';

const hash = (bytes) => createHash('sha256').update(bytes).digest('hex');
const initialOverlays = new Set(['pilot-boundary', 'wetlands', 'floodplain', 'hydrography', 'parks-open-space']);
function firstCoordinate(geometry) {
  let coordinates = geometry?.coordinates;
  while (Array.isArray(coordinates?.[0])) coordinates = coordinates[0];
  return Array.isArray(coordinates) && coordinates.length >= 2 && coordinates.every(Number.isFinite) ? coordinates.slice(0, 2) : null;
}

// The caller must first make a disposable copy under this checkout's ignored tmp.
// No writes, migrations, renames or deletion ever target snapshotDir.
export async function prepareSnapshot(root, snapshotDir, fixturePath) {
  const source = await realpath(snapshotDir);
  const tmp = await realpath(join(root, 'tmp'));
  const contained = relative(tmp, source);
  if (isAbsolute(contained) || contained === '..' || contained.startsWith(`..${sep}`)) throw new Error('--snapshot-dir must resolve inside this checkout\'s ignored tmp directory (a disposable copy)');
  const fixture = {}, sources = {};
  for (const name of ['development_records', 'environmental_overlays', 'source_health']) {
    const bytes = await readFile(join(source, `${name}.json`));
    sources[name] = { sha256: hash(bytes), bytes: bytes.length };
    fixture[name] = JSON.parse(bytes.toString('utf8'));
  }
  if (!Array.isArray(fixture.development_records) || !Array.isArray(fixture.environmental_overlays)) throw new Error('Snapshot collections must be arrays');
  const record = fixture.development_records.find((item) => ['layout', 'preliminary', 'final', 'issued_permit'].includes(item.status) && ['subdivision', 'building_permit'].includes(item.development_type) && ['high', 'medium', 'low'].includes(item.confidence_level) && item.centroid?.length === 2);
  const overlay = fixture.environmental_overlays.find((item) => initialOverlays.has(item.id) && item.features?.features?.some((feature) => firstCoordinate(feature.geometry)));
  await writeFile(`${fixturePath}.source-checksums.json`, JSON.stringify({ source_kind: 'disposable_local_snapshot', files: sources }, null, 2) + '\n');
  if (!record || !overlay) throw new Error('Snapshot has no selectable default-filter record or enabled legacy overlay. No readiness time can be measured; source checksums were retained.');
  let featureCount = 0;
  for (const layer of fixture.environmental_overlays) {
    for (const [index, feature] of layer.features.features.entries()) {
      featureCount++;
      feature.properties = { ...feature.properties, fixture_feature_id: `snapshot-${layer.id}-${index}` };
    }
  }
  const feature = overlay.features.features.find((item) => firstCoordinate(item.geometry));
  const serialized = JSON.stringify(fixture) + '\n';
  const manifest = {
    schema_version: 1, profile: 'local_snapshot', seed: null, source_files: sources,
    note: 'Disposable copy; only feature identity properties added for rendered-feature assertions. Original source checksums above. Probe is a geometry boundary vertex; failure to render remains a failed precheck.',
    development_records: fixture.development_records.length, environmental_features: featureCount,
    expected: { first_development: { public_id: record.public_id, title: record.title, centroid: record.centroid } },
    overlay_probes: [{ overlay_id: overlay.id, overlay_name: overlay.name, feature_id: feature.properties.fixture_feature_id, coordinate: firstCoordinate(feature.geometry) }],
    bytes_utf8: Buffer.byteLength(serialized), sha256: hash(serialized)
  };
  await writeFile(fixturePath, serialized);
  await writeFile(`${fixturePath}.manifest.json`, JSON.stringify(manifest, null, 2) + '\n');
  return manifest;
}
