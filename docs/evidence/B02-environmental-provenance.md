# B02 shadow environmental provenance acceptance

The isolated owning scenario passed on clean code
`932988169f4387c27f2f059b04fd72727072a031`, based on actual merged main
`66fb469b6f511d5db710c608c5e1c0e34b8d3aa5`. Run
`2026-09-27T09-56-28-530Z-afb79c6c` used exact Compose project
`urbanization_t01_e8e8b2fca0f6`. The runner exited zero, and a separate check
found zero project-labelled containers, volumes and networks. Root independently
verified the result and cleanup before assigning the next shared-stack run.

```text
node scripts/run-integration.mjs --suite api --scenario b02-provenance
```

The [exact generated manifest](b02/owning-manifest.json) records migration/owning
head, fixture and image identities, successful separate copied-database gate and
cleanup. The API image was
`sha256:61e0933be42fc720df72bfe326676ddb4ae271cc930ffbfce9407d3b267a7a14`;
the PostGIS image digest was
`postgis/postgis@sha256:44126d872ac91993766c341e369c539e8196614321765d36a6f1bab0419a5fa5`.
Alembic upgraded through `20260927_0009`, whose actual parent is
`20260924_0008`.

## Observed proof and recovery

The local official-shaped HTTP fixture produced 70 features over three retained
pages, including multipart geometry and holes, plus a separate complete empty
observation. The [sanitized capture summary](b02/capture-summary.json) records
seven nonempty and four empty requests, zero retries, and 17,461 decoded HTTP
entity bytes altogether. Geometry page artifact sizes differ from transport byte
counts because D01 writes its retained FeatureCollection encoding. No official
source API was called. Geometry, private fixture attributes and scope query bodies
remain in ignored local artifacts and private synthetic object storage.

The [exact generated results](b02/owning-results.json) show:

- Original control bytes rederived reconciliation; new deterministic whole P03
  envelope bytes were uploaded before the complete required-set seal.
- Ordinary CLI replay returned identical input/version/proof identities; recovery
  succeeded after checksum-authorized removal of source staging files.
- Same-count geometry edits and attribute edits with unchanged stored fingerprints
  refused proof. Twelve preexisting parent metadata/count/bounds/diagnostics edits,
  unmanaged extra rows and stale prepared revisions refused.
- Both parent-first and noncooperating feature-tuple-first lock cases observed
  `40P01`; their transactions rolled back. The managed-identity partial index was
  eligible under representative EXPLAIN with sequential scan disabled for the small
  fixture, rather than asserting a production planner choice.
- Seal/proof/link insertion rolled back together under injected failure. Both raw
  reference race orders, late run moves and unrelated proof links refused.
- Normal-role content/revision/identity mutations refused; operational timestamps
  and ordinary artifact-copy audit stayed supported. Oversized proof insertion and
  an explicitly different expected provider refused.
- Full custom-format `pg_dump`/`pg_restore` into the separate empty `b02_restore`
  target restored schema, data and post-data triggers. Ordinary bridge CLI replay
  and DB-only gates passed for empty and nonempty proofs. Data-only replay into an
  existing trigger-bearing schema is a different operation and is not claimed.

The original processed development/environmental/source-health snapshot checksum
remained `0996e100b2471d2de5d486831ab25e8cacb1946fd6d9a58739304c69ca978e1d`.
P03 coverage stays unknown. This attestation binds retained observations to exact
P03 content; it is neither an upstream cryptographic signature nor legal clearance.
P04b activation and O04 owner/use decisions remain separate gates.

Capture and attestation trust includes the controlled collector/CLI/verifier and
the principals allowed to write proof rows. SQL immutability guards protect
existing bound content; they do not authenticate an arbitrary proof INSERT by a
malicious DB writer using the same app role. The DB-only activation gate assumes
its recorded proof was created by the trusted verifier. Restricted operator and
DB-writer access is part of this contract, independently of the exclusion for
superusers disabling triggers. The gate still requires the caller's explicitly
selected provider identity.

## Honest diagnostics and representations

Two preceding owning attempts did not pass. The
[ce09 manifest](b02/failed-ce09-manifest.json) stopped at SQLAlchemy treating a
JSON literal's `:true` as a bind parameter; the fixture now uses
`jsonb_build_object`. The [ec933 manifest](b02/failed-ec933-manifest.json) reached
attestation/CLI replay but stopped at an overly narrow refusal-state expectation.
A tiny fresh normal-role migration diagnostic then observed ordinary TRUNCATE's
foreign-key `0A000` refusal and cascading TRUNCATE's B02 `P0001` guard separately,
with unchanged data/proof counts. Its [exact generated result](b02/truncate-diagnostic.json)
records this diagnostic, which is separate from complete owning acceptance. Both
outcomes now have independent assertions in the final owning matrix. The ignored
diagnostic wrapper's first attempt rejected a fractional Node timeout before SQL;
that attempt also cleaned up and is not reported as a test pass.

[Checksums](b02/checksums.json) hash the exact committed file bytes. Manifests,
owning results and diagnostic results are copied without transformation. The capture
summary explicitly documents its selected-field transformation and separately names
the original private report digests; its committed digest covers the summary itself.
No committed digest is presented as the digest of a different representation.

Static verification on the reviewed harness dependency and equivalent actual-main
runtime patch: 458 API tests, mypy across 60 app files, Ruff, five harness Node tests,
runner syntax and readiness-plan validation passed. Fixture-only corrections were
linted and then exercised by the final clean owning run. Review/CI status belongs to
the current PR head; this local proof does not substitute for those checks.
# Additive guard-index review correction

## Integrated P04a fixture correction and owning proof

The P04a reverse-insertion fixture formerly renamed a managed parent identity.
Migration0009 correctly refuses that reassignment. The fixture now independently
seeds the same source/version in a separate disposable `p04a_replica` database,
with ordinary Alembic head upgrade and reversed feature insertion order. It does
not clone a busy database, disable triggers, or modify original identity. This
is a separately seeded replica comparison, not a backup-restore test.

Clean `5cd7445` run `2026-09-27T10-41-39-123Z-47631b28` failed at exact backend
equality: the freshly migrated replica lacked optional extensions installed by
the locked PostGIS image initialization. Its failed manifest and replica result
remain committed. The correction mirrors the image's fixed four-extension set
and verifies exact installed versions before ordinary migration; backend and
all checksum assertions remain intact. No production identity guard changed.

Clean `91701c6832ec536f91e8039cce2badc4e4cb0c69` owning command
`node scripts/run-integration.mjs --suite api --scenario display-builder`, run
`2026-09-27T10-54-31-684Z-9cfd5878`, passed against actual migration0009.
Original and replica extension versions, complete PostGIS execution identity,
display/source/band/part checksums match. Original canonical layer key, geometry
and screening results remain unchanged. Both phases and bounded backend/extension
diagnostics are retained in exact generated JSON with checksums. Both attempts'
exact project containers, volumes and networks were independently verified absent.

CI now uploads an explicit diagnostic allowlist: top-level JSON/log/PNG,
Playwright outputs including XML, P04a JSON/SVG/PNG, P03 results and scenario
`*-data/results.json`. Raw private fixture objects/staging, environment files and
database dumps are deliberately excluded. This avoids traversing root-owned
private object files while retaining owning results and cleanup manifests.

The retained clean `9329881` local owning proof predates two additive indexes:
`environmental_attestations(source_key, run_id)` and
`environmental_attestation_references(reference_id)`. They support the exact
SQL guard predicates without changing guard semantics. Migration0009 and ORM
metadata both declare them. Fresh exact-head CI exercises actual migration and
normal-role PostgreSQL EXPLAIN assertions, recording eligible index names in the
owning results. On this small fixture, disabling sequential scans demonstrates
index eligibility only; it does not establish production planner choice or cost.
The old local artifacts are unchanged and do not claim post-index acceptance.

