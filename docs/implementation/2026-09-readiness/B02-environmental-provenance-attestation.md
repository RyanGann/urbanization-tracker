# B02 — Bind durable complete scoped evidence to the exact environmental import

Execution status: [plan.json](plan.json), entry `B02`. Prepared September 27, 2026.

| Field | Assignment |
| --- | --- |
| Track / gate | Data quality / G1 |
| Depends on | [B01](B01-control-response-evidence.md), [P03](P03-canonical-environmental-storage.md), [O01](O01-durable-artifact-uploads.md) |
| Review | Lead review |
| PR boundary | One additive shadow-only provenance bridge PR. |

Read [contracts](CONTRACTS.md), [testing instructions](TESTING.md),
[handoff rules](DISPATCH.md), and [P04](P04-environmental-display-derivatives.md).

## Problem and intended result

A validated P03 import does not prove source completeness. A D01 report or O01
seal does not prove that exact P03 input came from that collection. Independently
verify durable original controls/pages and bind their reconciliation to the exact
P03 layer/data version/input checksum with an immutable attestation. Count equality
alone is insufficient. Existing copied snapshots and control-less runs cannot
be retroactively promoted by a caller's checksum assertion.

## Code to inspect

- [D01 collector](../../../apps/api/app/ingestion/scoped_arcgis.py)
- [P03 importer](../../../apps/api/app/ingestion/environmental_import.py)
- [models](../../../apps/api/app/models.py)
- O01 artifact manifest/service/sink modules after their final merge.

## Implementation steps

1. Add immutable attestation FK to exact P03 layer and normalized typed artifact
   links with RESTRICT FKs. Bind layer key/data_version/source checksum/importer
   and bridge formats, source/run/sink, O01 seal digest, report, reviewed scope/
   boundary/context/query hashes, ordered page/control proof and reconciliation.
   Enforce update/delete immutability in DB; additive migration at current head.
2. Outside C02 lock, stream-read typed O01 references and verify exact byte length/
   SHA256. Parse B01 ORIGINAL controls to rederive count and stable initial/final
   IDs or offset count/edit-version. Validate role/source/run/query identity and
   reviewed scope. Reject canary, error, missing controls and incomplete proof.
3. Deterministically stream ONE new canonical FeatureCollection from verified
   pages, preserving original geometry and declared identity/property normalization.
   Upload this input in the same complete required set BEFORE O01 sealing. Never
   attest an arbitrary supplied file based on matching counts. Keep <=1,000 pages,
   <=1,024 refs and explicit body/descriptor/ID/time/total-byte caps; no whole
   geometry collection in memory. Fixed production allowlist; test-only injection.
4. Ordinary P03 shadow-import those exact durable input bytes with coverage unknown.
   Require validated, zero rejects/duplicates, exact scope/options/checksum/version,
   and source-ID/P03-normalized import_fingerprint set equality. Compare normalized
   fingerprints, not raw JSON-versus-WKB hashes. Preserve P03's complete-coverage
   CLI prohibition and immutable version hashing.
5. After all I/O/traversal, acquire short C02 transaction; reread exact P03 state
   and typed refs, call O01 exact required-set/source/run/sink verifier, then insert
   seal/attestation/links atomically. Identical replay is idempotent; changed proof
   for an immutable version conflicts. A crash leaves shadow data/no attestation.
6. Expose a bounded DB-only `require_environmental_provenance` helper for a caller
   holding C02 lock. Compare expected layer/version/input checksum/attestation,
   P03 validated state, pre-existing seal and exact verified required references.
   No remote reads, hashing or full geometry scan under lock; no auto-sealing a
   different set. P04b separately checks bands/pointer revision and O04 clearance.

## Acceptance and verification

- [ ] Synthetic official-shaped local HTTP fixture has >2 pages, holes/multipart,
  reviewed small synthetic scope, all B01 controls/O01 refs, new canonical input,
  P03 import and attestation. No production test bypass or new source.
- [ ] Replay input/version/proof digests and normalized source-ID/fingerprint sets
  match; original coordinate hashes stay unchanged.
- [ ] Refuse missing/tampered controls, forged report, equal-count changed IDs,
  query/source/role substitution, rejected/duplicate data, wrong/missing/extra/
  optional refs, unverified/wrong-sink copies, page-order/checksum swap, different
  input/version, edited/failed P03 row, prematurely sealed subset and cap overflow.
- [ ] Real PostGIS tests verify concurrent audit/ref changes, atomic rollback,
  replay/conflict, durable-only recovery, bounded locks and DB-only read gate.
- [ ] Upgrade empty/copied prior DB additively. Downgrade preserves evidence/
  attestation tables or explicitly refuses destructive downgrade.
- [ ] Run affected lint/types/tests and real scenario; retain exact SHA, migration,
  fixture hashes and measured bounds. Codex review and green CI; root merges.

## Rollout and recovery

B02 may merge shadow-only without owner rights choices. Preserve previous data
and immutable artifacts/attestations. Missing proof leaves no public pointer or
tile URL. O04 source/use/decision revision is a separate public-display gate,
never inferred from technical completeness or a successful upload.

## Outside this PR

No P04 display generation/pointer/catalog activation, live refresh, public source
redistribution, code-license choice, deployment or email.

## Agent handoff

> Implement B02 only after B01, P03 and final O01 merge. Build the durable exact
> input/version attestation and read gate with synthetic positive and real PostGIS
> failure/recovery evidence. No complete-coverage CLI escape hatch. P04b owns
> activation and O04 owns public-display permission. Request review/green CI.
