# C10 — Backfill historical agenda identity and decisions with reviewed mappings

Execution status: [plan.json](plan.json), entry `C10`. Prepared September 27, 2026. This follow-up was previously called the C04b historical backfill phase. C04 evidence records the conditional release gate and read-only inventory; this guide defines a separate implementation PR.

| Field | Assignment |
| --- | --- |
| Track / gate | Correctness / G1 |
| Depends on | [C04](C04-agenda-revision-retention.md), [O01](O01-durable-artifact-uploads.md) |
| Review | Lead review |
| PR boundary | One guarded operator backfill command and copied-database verification PR. |

Read the shared [contracts](CONTRACTS.md), [testing instructions](TESTING.md), [handoff rules](DISPATCH.md), and [C04 evidence](../../evidence/C04-agenda-revisions.md). C10 is planned, not implemented. It is a release requirement only if the C04 read-only inventory identifies historical gaps that an exact verified source replay cannot cover. A recorded zero-gap inventory can satisfy this conditional gate without running a backfill.

## Problem and intended result

Older retained agenda documents and decisions may lack immutable aliases, revision evidence or legacy decision baselines, especially outside the recent fetch window. C04 deliberately preserves these rows instead of guessing their identity. Provide an operator-reviewed, auditable way to attach the missing history without changing any existing candidate/public ID, decision, note or published snapshot.

## Code to inspect

- `apps/api/app/ingestion/agenda_inventory.py`: read-only gap inventory.
- `apps/api/app/ingestion/agenda_store.py`: logical aliases, revision evidence and append-only events.
- `apps/api/app/transactional_store.py`: C02 locked item mutations and expected state reads.
- `apps/api/app/ingestion/artifact_manifest.py`: O01 verified PDF/text reference evidence.
- `apps/api/app/seed_store.py`: authenticated decision exports.

These are starting points. Put the guarded import in a small operator-specific module; reuse C04 identity/history and O01 verification functions. Do not add a competing publication path.

## Implementation steps

1. Define a versioned mapping/import format with explicit legacy document/candidate/public IDs, the intended logical identities, exact verified PDF/text references and checksums, expected current state/revisions, actor, nonempty reason, input database snapshot checksum and decision-export checksum. Bind the mapping's own checksum to the audit run. Operators must review each mapping against authoritative source evidence; title, phase, ordinal or page similarity cannot establish identity.
2. Add a no-write dry run that inventories gaps, validates every mapping/reference/checksum and produces a bounded proposed change report. Report conflicting aliases, IDs, decisions, revision expectations, ambiguous evidence and unrelated rows. Refuse the run without partial mutation if any mapping is unsafe, stale or unverified. Never silently skip a refusal and report the batch successful.
3. Apply the exact reviewed mapping under C02's canonical lock, reading expected state after the lock. Create only missing immutable aliases/revisions/marked legacy baseline decision events and an audit receipt containing actor/reason/input checksums. Preserve original IDs and known actor/time; mark unavailable legacy actor/time honestly. Do not invent a decision timestamp.
4. Make apply idempotent using the mapping checksum and recorded receipt. An identical completed mapping changes nothing on repeat; a conflicting replay refuses. Existing incompatible immutable evidence or a newer reviewer decision refuses rather than overwriting it. Recheck source artifact verification in the same transaction.
5. Verify the resulting inventory and reconciled counts/IDs/decisions/notes against the pre-run export. Published records, record versions, publication events and public content must be byte-for-byte unchanged. No notification or publication event may be created by this historical backfill.
6. Record exact source, database/export/mapping checksums, tested SHA, commands, dry-run/refusal/apply/replay results and recovery evidence. Run against a copied database with copied O01 artifact manifests/objects before proposing any rollout.

## Acceptance and verification

- [ ] Read-only dry run writes no database rows/files, manifests or source objects, and lists every proposed attachment and refusal.
- [ ] Ambiguous title/ordinal matches, wrong artifact pair/checksum, conflicting identity, changed decision/revision, missing reason and mismatched input database/export checksum each refuse without partial mutation.
- [ ] Two apply attempts for identical reviewed mappings are idempotent; concurrent reviewer changes result in CAS refusal with the newer decision intact.
- [ ] Copied-database apply retains every original document/candidate/public ID, decision, note, known actor/time and published snapshot; a repeat adds no history/event.
- [ ] Injected failure after staged history writes rolls the entire PostgreSQL batch back. Restore the pre-run copied database plus its O01 manifest/object references and verify inventory/export/public snapshots match the baseline.
- [ ] The post-run inventory closes only mapped gaps and leaves unrelated unresolved observations visible. Preserve evidence for zero-gap conditional release decisions as well as actual backfills.
- [ ] Run focused unit, real PostgreSQL/API and copied-database recovery checks with exact SHA and fixture checksums. Update the guide's manifest status/evidence only for checks actually run.

## Rollout and recovery

Stop agenda/reviewer writes for the explicit maintenance import, back up the database and its O01 manifests/objects, and retain a decision export. Approve a concrete dry-run report and mapping checksum before any production apply. Recover by restoring the complete pre-run database plus matching artifact evidence; never delete selected revision/event rows to simulate rollback. Keep old published snapshots available while a mapping is refused or awaits review.

## Outside this PR

No fuzzy matching, automatic identity guessing, archive crawling, geometry correction, publication changes, retraction, notification delivery, or general database migration tool. Do not edit applied migrations or silently relabel historical decisions.

## Agent handoff

> Implement C10 only after C04 and O01 merge, and only when a retained inventory shows gaps requiring explicit mapping. Build a no-write dry run plus an idempotent expected-revision apply with actor/reason and input checksums. Demonstrate refusal, preservation and restore on a copied database. Do not mutate the working snapshot, publish, deploy or send mail.
