# C03 source identity and batch merge evidence

## Implementation boundary

C03 preserves existing public IDs through an authoritative source registry, adds
source/scope/run batches and observations, and merges source items under the C02
transaction. A versioned public-content fingerprint excludes checked timestamps
and private raw fields. Exact source anchors, discovery dates and existing URLs
are retained. Complete-scoped missing observations preserve canonical records;
capped/unknown/partial/failed source batches never infer disappearance.

Live source ingestion now requires PostgreSQL. Artifact and demo preview reads
remain supported, but source ingestion against those backends is rejected before
fetching or writing. See the source ingestion runbook for copied-backup dry run,
reviewed digest application, mapping export and private raw-observation recovery.

## Development evidence before final integration

These runs preceded final main/catalog integration and are not final-head claims.

- Locked Python 3.12 Ruff, mypy and the full backend suite passed (106 tests) before
  the latest backfill/fingerprint review fixes. Subsequent focused tests covered
  distinct discovery dates, invalid dates, duplicate public IDs, address/parcel
  changes and the actual public proximity-flag fields. The final checks below must
  supersede these development results.
- Real-stack run `2026-09-22T14-19-41-207Z-afe7f34a` passed using isolated project
  `urbanization_t01_260b780d5e12`; cleanup removed that exact project. The manifest
  records base `1fdf201b3b2c4c7a227f08fe8fc73fe6d8be47eb` with
  `working_tree_dirty: true`.
- Fixture SHA-256:
  `932eacb03655a3dee1a2838abf9ddf8d5dfa44f744482408611b61a2561bbee2`.
  Scenario result SHA-256:
  `b9127000aae57559093b7d33ea647edc74af36bffbcd77371faad1f691106e70`.
- The run verified ambiguous backfill refusal, append/replay, conservative
  coverage, explicit complete-empty missing observations, a real PostgreSQL lock
  waiter concurrent with HTTP submission, source-aware adapter raw/history/health
  retention, failed environmental replacement protection, and the full Madison
  ingestion entry point using fixture ArcGIS responses.
- The Madison path retained two historical raw observations, four canonical
  records and a 1,041-byte raw artifact with manifest/checksum agreement. A custom
  format dump was restored into a separate database; all three registry mappings
  matched and the restored API resolved `bookmarked-legacy-id` with discovery date
  `2025-01-02`.

Command:

```text
node scripts/run-integration.mjs --suite api --scenario c03-source-identity
```

Ignored evidence is under `tmp/integration/<run-id>/`: `manifest.json`,
`c03-data/results.json`, service logs and cleanup result. No upstream refresh or
original saved snapshot mutation was performed.

## Final integration verification

Record the clean committed runtime SHA, locked check commands/results, latest
real-stack manifest/checksums, P02 catalog-preservation proof, and final PR/CI
review evidence here before marking the guide complete.
