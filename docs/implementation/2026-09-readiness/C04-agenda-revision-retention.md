# C04 — Retain agenda documents and reviewer decisions across refreshes

Execution status: [plan.json](plan.json), entry `C04`. Guide baseline: `dbdaf099f31bc0444fe202aaf2ee65b3c9268d34`. Prepared September 19, 2026.

| Field | Assignment |
| --- | --- |
| Track / gate | Correctness / G1 |
| Depends on | [C02](C02-transactional-store-foundation.md), [C03](C03-stable-source-identity.md) |
| Review | Lead review |
| PR boundary | One agenda identity/merge PR. |

Read the shared [contracts](CONTRACTS.md), [testing instructions](TESTING.md) and [handoff rules](DISPATCH.md) first. The steps below define this guide's scope; use its manifest entry and evidence to determine current capability.

## Problem and intended result

Agenda ingestion replaces the last three documents and candidates. Rejected candidates become pending on unchanged replay, and older documents disappear.

## Code to inspect

- [apps/api/app/ingestion/agenda.py](../../../apps/api/app/ingestion/agenda.py)
- [apps/api/app/ingestion/agenda_pipeline.py](../../../apps/api/app/ingestion/agenda_pipeline.py)
- [apps/api/app/ingestion/connectors/agenda.py](../../../apps/api/app/ingestion/connectors/agenda.py)
- [apps/api/app/phase3_store.py](../../../apps/api/app/phase3_store.py)
- [apps/api/app/schemas.py](../../../apps/api/app/schemas.py)

These are inspection starting points, not a requirement to put all new code in existing large modules. Prefer a small purpose-specific module where the guide introduces a new service. Add migrations at the current Alembic head; never edit an applied migration.

## Implementation steps

1. Separate logical document identity from blob SHA-256 and document revision. Prefer an authoritative meeting/document identifier; otherwise persist a canonical source URL/date key with collision diagnostics. A different download URL alone must not erase known provenance.

2. Define candidate identity from an authoritative case/application ID when available, scoped by logical document and an immutable source item key. Otherwise allocate a persisted internal candidate ID on first import and record the observation-to-ID mapping; identical artifact/observation replays reuse it. Titles, phases, page positions and ordinals are matching evidence, never identity inputs. If a changed document lacks a stable item anchor, quarantine the unmatched observation for explicit identity resolution: link it as a revision of an existing candidate or deliberately create a new candidate. Provide a narrow audited operator mapping/import command for this resolution, with expected revision checks; never detach prior decisions or auto-merge by mutable text.

3. Upsert documents and candidate revisions through C02. An unchanged content fingerprint preserves reviewer status, notes, actor, decision timestamp and revision. A materially changed candidate creates a new pending revision while preserving the previous decision and published snapshot.

4. Keep older documents even when only the newest three are fetched in one run. Record superseded/withdrawn observations rather than deleting audit context. Missing archive discovery and known-PDF fallback must be visible in freshness/coverage health.

5. Remove the fictional city-center location for unlocated agenda items. Represent staged geometry as nullable with an explicit location_required reason; publication will be blocked until a reviewer supplies supported geometry.

6. Preserve source revisions and decision exports through restart and migration; do not silently overwrite a newer decision with an imported older snapshot.

## Acceptance and verification

- [ ] Reject -> replay identical agenda -> still rejected with the same notes; approve -> replay -> one published record; changed content -> pending new revision with old decision retained.
- [ ] Fetch three newer documents -> prior documents and their candidates remain accessible.
- [ ] Changed source_status retains stable candidate identity. Without an authoritative item ID, title/phase edits and reordered pages enter identity resolution; explicitly linking the observation preserves the prior candidate ID, decisions and history. Identical replays reuse the persisted mapping, and ambiguous matches are never automatically merged or published.
- [ ] No-location candidate is visible for review but cannot be published at the default Huntsville center.
- [ ] Run the affected existing lint/types/tests plus the real-stack scenarios above; retain exact commands, SHA, fixture checksum and results. Do not claim an unrun check passed.
- [ ] Update API/client schemas and user-facing error states together when their contract changes; report any departure from the shared contract before merging.

## Rollout and recovery

Backfill existing document/candidate IDs through explicit mappings and preserve originals. Keep old published snapshots while uncertain matches await review.

## Outside this PR

No OCR expansion, automated location guessing, automatic duplicate merging, or wholesale archive crawling.

## Agent handoff

> Implement C04 only, after its dependencies are merged. Implement revision-aware agenda merges and prove that unchanged refreshes cannot erase reviewer decisions or document history. Use the acceptance checklist above as completion criteria. Return a focused diff, validation evidence, migration/rollback notes and any remaining risks. Do not deploy, send real email, refresh the working snapshot, or expand into another guide.
