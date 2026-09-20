# O02 — Update hosted configuration and readiness checks for the new contracts

Execution status: [plan.json](plan.json), entry `O02`. Guide baseline: `dbdaf099f31bc0444fe202aaf2ee65b3c9268d34`. Prepared September 19, 2026.

| Field | Assignment |
| --- | --- |
| Track / gate | Operations / G3 |
| Depends on | [S01](S01-frontend-dependency-update.md), [C01](C01-explicit-data-modes.md), [P05](P05-versioned-vector-tile-api.md), [P07](P07-bounded-development-map-api.md), [O01](O01-durable-artifact-uploads.md), [S03](S03-watch-confirmation-unsubscribe.md) |
| Review | Lead review |
| PR boundary | One configuration/preflight PR; no deployment action. |

Read the shared [contracts](CONTRACTS.md), [testing instructions](TESTING.md) and [handoff rules](DISPATCH.md) first. The steps below define this guide's scope; use its manifest entry and evidence to determine current capability.

## Problem and intended result

The current Blueprint is scaffolding, and the documented services were not verified live. New spatial indexes, explicit data mode and durable artifacts require readiness checks beyond process liveness.

## Code to inspect

- [render.yaml](../../../render.yaml)
- [.env.example](../../../.env.example)
- [apps/api/app/config.py](../../../apps/api/app/config.py)
- [apps/api/app/deployment_preflight.py](../../../apps/api/app/deployment_preflight.py)
- [apps/api/app/main.py](../../../apps/api/app/main.py)
- [docs/deployment.md](../../deployment.md)
- [docs/operations-monitoring.md](../../operations-monitoring.md)

These are inspection starting points, not a requirement to put all new code in existing large modules. Prefer a small purpose-specific module where the guide introduces a new service. Add migrations at the current Alembic head; never edit an applied migration.

## Implementation steps

1. Keep /health as cheap liveness. Add a separate bounded readiness check for database connectivity/migration revision, required indexes, initialized canonical store, active layer/index compatibility and runtime configuration. Report source freshness/coverage separately from process availability.

2. Require live mode, Postgres stores, reviewer API token, explicit HTTPS/CORS web/API origins, verified artifact configuration and secure proxy settings in hosted preflight. Explain every failed condition with a remediation command.

3. Update Blueprint/env documentation for the actual web/API split, catalog/tile cache headers, static SPA deep links, migration/rebuild commands and bounded worker jobs. Keep ingestion and real email disabled by default.

4. Document edge protection for both /review and /api/reviewer/*, and test API authentication independently of the edge. No secret may be embedded into the static build.

5. Specify backup ownership, retention, object-store retention, monitoring thresholds, source/matcher/delivery backlog alarms and a rollback runbook. Missing provider/account details remain concrete deployment inputs, not invented resources.

6. Describe resource assumptions and verify that deployment health checks cannot trigger full artifact reads, tile rebuilds or expensive source fetches.

## Acceptance and verification

- [ ] Configuration matrix: demo mode, missing token, wildcard/untrusted origins, missing PostGIS, wrong migration, absent index and unverified storage fail preflight.
- [ ] Healthy test environment passes readiness while a stale source still reports its separate source-health warning.
- [ ] Static deep links for detail/review/confirmation/unsubscribe resolve correctly under the proposed hosting rules.
- [ ] Existing Render Blueprint validation and API auth checks pass; no cloud resources are created by tests.
- [ ] Run the affected existing lint/types/tests plus the real-stack scenarios above; retain exact commands, SHA, fixture checksum and results. Do not claim an unrun check passed.
- [ ] Update API/client schemas and user-facing error states together when their contract changes; report any departure from the shared contract before merging.

## Rollout and recovery

Reviewable templates and runbooks only. A real deployment is a later explicit action after O03 evidence and owner inputs; do not assume old hostnames still exist.

## Outside this PR

No auto-provisioning, real credentials, enabling public submissions/email prematurely, or using liveness as proof of readiness.

## Agent handoff

> Implement O02 only, after its dependencies are merged. Update deployment templates and fast readiness/preflight checks to enforce the new live-data and persistence contracts, leaving external rollout unperformed. Use the acceptance checklist above as completion criteria. Return a focused diff, validation evidence, migration/rollback notes and any remaining risks. Do not deploy, send real email, refresh the working snapshot, or expand into another guide.
