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

Initial final verification on committed `b4a32c4fb12d4cf4dc9c6b94b300baf811fa3cb0`:

- Locked Python 3.12: `ruff check .`, `mypy app`, and `PYTHONPATH=/src/apps/api pytest` passed: 122 tests passed, with two upstream FastAPI/Starlette deprecation warnings.
- Real-stack clean run `2026-09-22T14-35-42-247Z-fa1b56ce` passed with `working_tree_dirty: false`; cleanup removed project `urbanization_t01_88af523756a9`.
- The restored API returned `bookmarked-legacy-id` with `date_discovered: 2025-01-02`; the restored mapping count was three. The result SHA-256 was `b9127000aae57559093b7d33ea647edc74af36bffbcd77371faad1f691106e70`.
- The same-UoW adapter test seeded a ready catalog layer, processed a failed environmental source refresh, and verified that the prior ready layer remained unchanged.

Codex review fixes were locally verified on committed runtime
`25065c4ed32708b6e3484d6081dcf3b036e4b184`:

- Locked Python 3.12: `ruff check .`, `mypy app` (38 source files), and
  `PYTHONPATH=/src/apps/api pytest -q` (122 passed; two upstream deprecation
  warnings). The worktree was clean for the real-stack run.
- Isolated PostgreSQL/API run `2026-09-24T04-27-07-382Z-fb369c04` passed;
  manifest `working_tree_dirty: false`, `outcome: passed`, and
  `cleanup_result: removed` for project `urbanization_t01_4db397920b52`.
  Fixture SHA-256 was
  `932eacb03655a3dee1a2838abf9ddf8d5dfa44f744482408611b61a2561bbee2`;
  scenario result SHA-256 was
  `8e49c1c16e0278d9c0955edfce80eb805c5b38d8d9e273474ee0ef746f964f8d`.
- New source anchors refused provisional public IDs owned by a manual canonical
  row or another registry mapping. Backfill dry run diagnosed a reverse public-ID
  owner and refused application without partial mappings; the PostgreSQL unique
  constraint rejected a second owner at the database boundary. Existing two-anchor
  candidate regression also produced zero backfill candidates.
- A refresh preserved the original `2025-01-02` discovery date in both the
  canonical and reviewer-facing staged record. Four fetched Madison rows yielded
  one accepted record after missing-ID and duplicate-anchor quarantine. A separate
  quarantine-only run yielded three seen, zero accepted, and three persisted
  rejected input rows with partial coverage and no inferred source-missing record.
- Identical raw rows survived separately: ten total raw observations remained
  after both Madison runs. A cross-source provisional-ID collision fixture
  quarantined both rows and attributed one rejection to each source. The restored
  database retained three registry mappings and the bookmarked public URL.

These local checks do not establish scoped source completeness, durable artifact
verification, a performance budget, or deployment readiness. PR #25 still needs
final-head Codex review and green GitHub CI before merge.
