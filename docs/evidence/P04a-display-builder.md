# P04a shadow display builder — real PostGIS evidence

Run on 2026-09-24 from the isolated `codex/p04a-display-builder` worktree:

```text
node scripts/run-integration.mjs --suite api --scenario display-builder
run_id: 2026-09-24T07-28-21-674Z-abcd3264
outcome: passed
cleanup_result: removed
result_sha256: 81519749f93f515d1836b95726fdc98f2c54a970672cb7db5e9a239778ef17a6
```

The disposable stack migrated through 0008 and built all five display bands
from five synthetic polygon-family features. It actually killed the builder
after the first committed two-feature checkpoint, resumed with a different
batch size, and replayed the validated result. It checked that original
EPSG:4326 EWKB SHA-256 and exact spatial screening count did not change. A
hole stayed one hole and a multipolygon stayed two components. The dense
polygon produced four parts at z17–18; all emitted parts had at most 153
vertices (limit 256). The selected viewport query used the projected GiST
index. The part-set SHA-256 after replay was
`23af6abfd2951fe0779420cb2ffe7c41cd2de03d5dd4f75231ea1d065d2265cc`.

The same run translated a stored part and updated its row digest; replay
refused the changed per-feature output digest. A deliberately failing PostGIS
statement inside one feature savepoint left the outer batch usable for the
next feature. A polygon outside the supported Web Mercator latitude failed
closed in every band. A failed/partial P03 import produced a validated *display*
diagnostic with `publicly_active=false`; after synthetic same-version P03
resume, the source snapshot hash yielded a new immutable display version while
the prior shadow build stayed intact. No public catalog or active pointer
changed. The run removed its Docker project.

The locked `c04-api-check:local` image subsequently passed `ruff check app
tests alembic`, `mypy app` (55 source files), and 31 affected unit tests
(`test_display_config.py`, `test_environmental_import.py`,
`test_environmental_output.py`, `test_ingestion_cli.py`). A follow-up changed
the source snapshot hash to stable source identities instead of database IDs;
the full real-stack scenario will be rerun after rebasing onto merged O01.

Machine-readable local artifacts are under
`tmp/agents/p04a/tmp/integration/2026-09-24T07-28-21-674Z-abcd3264/`
(`manifest.json`, `p04a/results.json`, `cleanup-result.json`). This test uses
synthetic geometry and does not establish production FEMA or wetlands coverage,
source rights, or public activation; P04b must check those independent gates.

The builder only inserts parts/results for a version and verifies them on
replay. Unique keys, restricted parent deletes, and the refusal to downgrade
protect version/checkpoint evidence, but the database does not prohibit a
privileged writer from updating an existing part. P04b retention will need
controlled deletion; any public activation must reverify the derivative and
source provenance rather than treating the P04a status as a DB write lock.
