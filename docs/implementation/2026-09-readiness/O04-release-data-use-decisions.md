# O04 — Prepare code-license, data-use, and public disclosure decisions

Status: **Planned; no application implementation in this guide.** Baseline: `dbdaf099f31bc0444fe202aaf2ee65b3c9268d34`. Prepared September 19, 2026.

| Field | Assignment |
| --- | --- |
| Track / gate | Operations / G3 |
| Depends on | [D01](D01-source-scope-pagination-canaries.md), [P02](P02-layer-catalog-startup-relief.md) |
| Review | Owner decision after prepared evidence |
| PR boundary | One documentation/configuration inventory PR. |

Read the shared [contracts](CONTRACTS.md), [testing instructions](TESTING.md) and [handoff rules](DISPATCH.md) first. New endpoints, settings, tables and runner commands below are **proposed work**, not existing capabilities.

## Problem and intended result

The project calls itself open source without a root LICENSE, and source redistribution questions remain unresolved. Basemap and environmental feeds each need their own attribution/use record.

## Code to inspect

- [README.md](../../../README.md)
- [docs/data-sources/huntsville-al.md](../../data-sources/huntsville-al.md)
- [docs/data-sources/madison-county-al.md](../../data-sources/madison-county-al.md)
- [docs/source-onboarding.md](../../source-onboarding.md)
- [docs/privacy-safety-checklist.md](../../privacy-safety-checklist.md)
- [docs/deployment.md](../../deployment.md)

These are inspection starting points, not a requirement to put all new code in existing large modules. Prefer a small purpose-specific module where the guide introduces a new service. Add migrations at the current Alembic head; never edit an applied migration.

## Implementation steps

1. Build a concise inventory of every source and provider used in the proposed alpha: owner, authoritative URL, retrieved terms/date, attribution, storage/display/redistribution scope, retention and unresolved restrictions. Public availability alone is not recorded as permission.

2. Prepare a concrete code-license recommendation with alternatives and dependency compatibility evidence. The repository owner selects the license; after that choice, add the exact root LICENSE and update package/README metadata. Do not infer a license from God’s Eye View's MIT license.

3. Link source decisions to stable catalog IDs and publication/export controls. A source with unresolved display permission remains withheld from public activation; reviewers can inspect its diagnostics without claiming public redistribution rights.

4. Prepare plain-language coverage/freshness, approximate geometry, environmental-screening and privacy disclosures. These must describe actual implemented behavior rather than disclaiming known defects.

5. Record the basemap provider decision/attribution and any budget or account prerequisites without creating accounts. Document a no-provider/unavailable UI state.

6. Produce a decision sheet containing ready-to-review text and exact unresolved choices. Routine coding may continue while these decisions are pending, but the public gate remains explicit.

## Acceptance and verification

- [ ] Every publicly enabled layer/source has a source-use record and visible attribution matching the catalog.
- [ ] No root license is represented as selected before the owner's choice; no unverified source is marked cleared.
- [ ] Check public UI/export fields against the privacy allowlist and source restrictions.
- [ ] Links and quoted terms are rechecked on the implementation date using primary sources.
- [ ] Run the affected existing lint/types/tests plus the real-stack scenarios above; retain exact commands, SHA, fixture checksum and results. Do not claim an unrun check passed.
- [ ] Update API/client schemas and user-facing error states together when their contract changes; report any departure from the shared contract before merging.

## Rollout and recovery

This prepares evidence and applies already selected choices. If a required owner decision is absent, finish the inventory/recommendation and report that exact remaining release gate; do not block unrelated engineering.

## Outside this PR

No legal conclusion about ambiguous terms, contacting source owners without instructions, or promoting reuse before a code license is selected.

## Agent handoff

> Implement O04 only, after its dependencies are merged. Prepare the concrete release/data-use decision sheet and source inventory, then apply only documented owner choices. Use the acceptance checklist above as completion criteria. Return a focused diff, validation evidence, migration/rollback notes and any remaining risks. Do not deploy, send real email, refresh the working snapshot, or expand into another guide.
