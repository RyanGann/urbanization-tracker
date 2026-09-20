# E01 — Add one authoritative protected-land or refuge layer

Execution status: [plan.json](plan.json), entry `E01`. Guide baseline: `dbdaf099f31bc0444fe202aaf2ee65b3c9268d34`. Prepared September 19, 2026.

| Field | Assignment |
| --- | --- |
| Track / gate | Environmental expansion / G4 |
| Depends on | [O03](O03-restricted-alpha-rehearsal.md), [P04](P04-environmental-display-derivatives.md), [D02](D02-authoritative-spatial-screening.md) |
| Review | Lead review |
| PR boundary | One source adapter/configuration PR for one dataset. |

Read the shared [contracts](CONTRACTS.md), [testing instructions](TESTING.md) and [handoff rules](DISPATCH.md) first. The steps below define this guide's scope; use its manifest entry and evidence to determine current capability.

## Problem and intended result

The original environmental goals include protected/public lands and refuges, but the current actual layers are only wetlands and floodplain.

## Code to inspect

- [docs/source-onboarding.md](../../source-onboarding.md)
- [docs/data-sources/huntsville-al.md](../../data-sources/huntsville-al.md)
- [apps/api/app/ingestion/pipeline.py](../../../apps/api/app/ingestion/pipeline.py)
- [apps/api/app/ingestion/proximity.py](../../../apps/api/app/ingestion/proximity.py)
- [apps/web/src/pages/MapPage.tsx](../../../apps/web/src/pages/MapPage.tsx)

These are inspection starting points, not a requirement to put all new code in existing large modules. Prefer a small purpose-specific module where the guide introduces a new service. Add migrations at the current Alembic head; never edit an applied migration.

## Implementation steps

1. Select one authoritative source for the Huntsville/Wheeler-refuge context, preferring a clearly licensed federal boundary dataset. Rediscover the current agency endpoint; an older FWS GIS link now redirects and is not sufficient evidence.

2. Record source version/date, boundary semantics, CRS, attribution and use restrictions. Distinguish administrative/refuge boundaries from land ownership, public access or designated critical habitat.

3. Implement one bounded ingestion adapter using D01 scope/coverage and O01 verified artifacts. Feed the existing canonical versioned environmental importer/display pipeline; do not add a separate map delivery mechanism.

4. Add a catalog category/legend and source detail text. If a screening relationship is added, use D02's original geometry, explicit rule version and conservative wording.

5. Include geometry/coverage fixtures, an opt-in small upstream probe and an isolated refresh test. Make layer activation contingent on source-use documentation and complete scoped data.

6. Record the next environmental sources as candidates only; do not pull national datasets merely because the source offers them.

## Acceptance and verification

- [ ] Fresh/replayed/failed ingestion maintains stable IDs, source versions and last-good layer behavior.
- [ ] Known refuge edge and out-of-scope points display/query correctly; attribution and boundary meaning are visible.
- [ ] Tile size/performance budgets remain within limits and original screening geometry is retained.
- [ ] Public descriptions do not imply all mapped land is publicly accessible or protected under the same designation.
- [ ] Run the affected existing lint/types/tests plus the real-stack scenarios above; retain exact commands, SHA, fixture checksum and results. Do not claim an unrun check passed.
- [ ] Update API/client schemas and user-facing error states together when their contract changes; report any departure from the shared contract before merging.

## Rollout and recovery

Enable one verified layer in the restricted alpha and collect resident/reviewer feedback before adding more categories.

## Outside this PR

No nationwide rollout, habitat inference, combined batch of several unrelated sources, or environmental-impact determinations.

## Agent handoff

> Implement E01 only, after its dependencies are merged. Add one verified protected-land/refuge source through the existing ingestion, tile and provenance contracts. Use the acceptance checklist above as completion criteria. Return a focused diff, validation evidence, migration/rollback notes and any remaining risks. Do not deploy, send real email, refresh the working snapshot, or expand into another guide.
