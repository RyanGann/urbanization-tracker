# B01 — Retain bounded original source-control response evidence

Execution status: [plan.json](plan.json), entry `B01`. Prepared September 27, 2026.

| Field | Assignment |
| --- | --- |
| Track / gate | Data quality / G1 |
| Depends on | [D01](D01-source-scope-pagination-canaries.md) |
| Review | Lead review |
| PR boundary | One bounded collector retention PR; staging only. |

Read [contracts](CONTRACTS.md), [testing instructions](TESTING.md) and
[handoff rules](DISPATCH.md). [B02](B02-environmental-provenance-attestation.md)
owns the durable artifact/import binding; no O01 runtime dependency is added here.

## Problem and intended result

D01 retains geometry pages and a sanitized report, but originally discarded
metadata, count and initial/final ID response bytes. Report assertions alone
cannot support independent coverage verification. Retain exact bounded control
bodies for new observations with typed source/run/query/role/checksum descriptors.
Old runs remain ineligible for B02 attestation without those original controls.

## Code to inspect

- [scoped_arcgis.py](../../../apps/api/app/ingestion/scoped_arcgis.py)
- [control_artifacts.py](../../../apps/api/app/ingestion/control_artifacts.py)
- [collector fixtures](../../../apps/api/tests/test_scoped_arcgis.py)

## Implementation steps

1. Retain response bodies before parsing, preserving HTTP-content-decoded bytes,
   whitespace, numeric spelling and key order. Stream into an observation-specific
   temporary file and atomically finalize only complete bounded bodies. Partial
   bodies never gain descriptors. Raw bytes remain private staging artifacts.
2. ID mode roles: initial metadata/count/IDs and final IDs. Offset roles: initial
   metadata/count and final count/metadata. Canary retains only actually queried
   controls and never adds a final-ID request. Roles bind source/run/scope version,
   query digest, fixed endpoint, method, operation, sequence, status, bytes and hash.
   Check the actual GET URL/POST form against trusted expected query values before
   capture; refuse extras/duplicate keys and redirects, even on injected clients.
3. Enforce four controls, 80 MiB total control bytes, 64 KiB descriptor budget and
   1,000 pages, alongside existing response/ID/request/time caps. At O01's 1,024
   reference cap, scope/report/canonical input plus four controls leave 1,017 page
   slots; the lower B01 page limit stays explicit. Never omit proof to fit caps.
4. Keep the production source allowlist. Synthetic endpoint injection is test-only.
   Reject unsafe/repeated roles and endpoint/operation substitutions; generated
   observation-specific names prevent replacing prior control proof. Sanitize
   diagnostics and never put response contents in report/log strings.
5. Do not seal a subset: B02 must add its canonical input before sealing the exact
   required set. No attestation table, public API, canonical health behavior,
   complete-coverage promotion or activation command is introduced here.

## Acceptance and verification

- [ ] Deterministic fixtures reproduce retained bytes/checksums exactly, including
  whitespace and Unicode, for ID and offset control sequences.
- [ ] Canary request cap remains unchanged; mismatched IDs retain honest controls
  and remain incomplete. Same-count changed IDs never claim complete coverage.
- [ ] Timeout/midbody interruption, invalid JSON, oversized bodies, byte/descriptor/
  role/page caps and deadline failures leave no finalized partial control file.
- [ ] Unsafe paths, invalid/repeated role, wrong endpoint/operation and private
  body leakage are refused. Replay does not overwrite earlier observation controls.
- [ ] Run affected Python fixtures, backend lint/types/tests and assigned D01 real
  API/PostGIS scenario. Record commands, exact head/fixture hashes and unrun checks.
  No additional official upstream call is needed for this retention-only change.
- [ ] Roadmap/schema/link validator, Codex review and green CI pass; root merges.

## Rollout and recovery

No migration/canonical transaction is needed. Staging failure cannot activate
data. Existing explicit attempt-health behavior stays unchanged. Interrupted
temporary files are cleaned only for this observation; new runs get fresh IDs.
B02 owns durable upload/recovery and evidence-preserving database migrations.

## Outside this PR

No public activation, source refresh, O01 seal, attestation, redistribution or
owner rights choice. O04 pending decisions permit isolated staging only.

## Agent handoff

> Implement B01 after D01/PR33 merge on fresh main. Add bounded original control
> retention and deterministic fixtures only. Keep B02 planned and P04's status
> unchanged. Update approved guide/dependency documentation and D01 implementation
> completion while preserving upstream reconciliation/rights as activation gates.
> Request review and green CI; root merges. No extra live source calls or deployment.
