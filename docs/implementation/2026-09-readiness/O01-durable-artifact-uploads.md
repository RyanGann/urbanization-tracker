# O01 — Upload and verify ingestion artifacts before activating data

Execution status: [plan.json](plan.json), entry `O01`. Guide baseline: `dbdaf099f31bc0444fe202aaf2ee65b3c9268d34`. Prepared September 19, 2026.

| Field | Assignment |
| --- | --- |
| Track / gate | Operations / G1 |
| Depends on | [C02](C02-transactional-store-foundation.md) |
| Review | Lead review |
| PR boundary | One artifact-storage adapter/manifest PR. |

Read the shared [contracts](CONTRACTS.md), [testing instructions](TESTING.md) and [handoff rules](DISPATCH.md) first. New endpoints, settings, tables and runner commands below are **proposed work**, not existing capabilities.

## Problem and intended result

The current manifest records intended storage URIs but does not actually upload raw source data. A restart or ephemeral disk loss can therefore sever provenance.

## Code to inspect

- [apps/api/app/ingestion/artifacts.py](../../../apps/api/app/ingestion/artifacts.py)
- [apps/api/app/ingestion/pipeline.py](../../../apps/api/app/ingestion/pipeline.py)
- [apps/api/app/ingestion/agenda_pipeline.py](../../../apps/api/app/ingestion/agenda_pipeline.py)
- [apps/api/app/config.py](../../../apps/api/app/config.py)
- [apps/api/app/deployment_preflight.py](../../../apps/api/app/deployment_preflight.py)

These are inspection starting points, not a requirement to put all new code in existing large modules. Prefer a small purpose-specific module where the guide introduces a new service. Add migrations at the current Alembic head; never edit an applied migration.

## Implementation steps

1. Add a minimal artifact sink interface with local and S3-compatible implementations. Test the object-store adapter against an isolated local emulator; do not provision a real bucket or select a paid provider in this PR.

2. Use immutable content-addressed keys with source/run metadata, byte size and SHA-256. Stream uploads, explicitly verify checksum/size, and distinguish pending/uploaded/verified/failed status in a durable database manifest.

3. Do not treat a multipart object ETag as a SHA-256 checksum. Store/verify checksum metadata or retrieve and hash in bounded verification where the provider lacks an integrity primitive.

4. Stage downloads and parsing outside the canonical transaction. In hosted mode, activation/publication of newly ingested source observations requires verified required artifacts. Upload failure retains the previous active data and a retryable manifest state.

5. Add resumable upload and integrity-audit CLI commands. Track local staging disk limits/cleanup only after durable verification; preserve raw documents, extracted text and source payload relationships.

6. Keep credentials server-side, avoid public access by default, and expose only licensed public source links through the web API. Document retention and restoration of both manifests and objects.

## Acceptance and verification

- [ ] Emulator upload/download checksum round trip; interrupted upload, duplicate retry, bad checksum and credential failure preserve accurate state.
- [ ] Failed upload cannot activate a new canonical/environmental version; retry succeeds without duplicate publication.
- [ ] Restart API/worker with empty local staging: verified artifacts remain locatable and recoverable.
- [ ] Manifest updates from two runs do not overwrite each other; logs never expose storage credentials or signed URLs.
- [ ] Run the affected existing lint/types/tests plus the real-stack scenarios above; retain exact commands, SHA, fixture checksum and results. Do not claim an unrun check passed.
- [ ] Update API/client schemas and user-facing error states together when their contract changes; report any departure from the shared contract before merging.

## Rollout and recovery

Ship with local mode for development and hosted ingestion still disabled. Configure real storage later, verify a small copied artifact set, then allow O03's rehearsal.

## Outside this PR

No public bucket, cloud provisioning, blanket redistribution permission, or claiming a URI proves durable upload.

## Agent handoff

> Implement O01 only, after its dependencies are merged. Implement verified durable artifact storage and publication gating, tested with a local object-store emulator. Use the acceptance checklist above as completion criteria. Return a focused diff, validation evidence, migration/rollback notes and any remaining risks. Do not deploy, send real email, refresh the working snapshot, or expand into another guide.
