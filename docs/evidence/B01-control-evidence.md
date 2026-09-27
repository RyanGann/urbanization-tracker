# B01 bounded original control-response evidence

New D01 observations retain original HTTP-content-decoded metadata/count/ID
response bytes before JSON parsing. Each private file binds its source/run,
reviewed scope, role/sequence, expected scoped-query digest, endpoint/method,
status, byte count and SHA-256. Geometry paging, canary request limits and health
coverage behavior remain unchanged. No durable seal, attestation or activation
is introduced; B02 owns those gates. Legacy reports without original controls
cannot be independently attested by copying their count/digest assertions.

Control capture is bounded to four files, 80 MiB total control bytes and 64 KiB
descriptors, with 1,000 page artifacts. Existing request/response/ID/time limits
still apply, and the collection deadline is checked while streaming responses.
The writer enforces its own byte bound. Generated observation UUID paths and
atomic no-replace finalization prevent prior control replacement; interrupted
temporary bodies are removed and never gain completed descriptors. Completed
invalid-JSON responses may be retained privately as honest diagnostics, without
raw body text entering public reports. Production sources remain allowlisted.

## Local checks

On implementation head `47af8c193825fb90880eb782ece26061e8020af4`, the existing
installed-dependency `c04-api-check:local` image ran these checks with the isolated
checkout mounted at `/workspace`, working directory `/workspace/apps/api`,
`--network none`, no Docker services:

```text
python -m ruff check app tests
python -m mypy app
python -m pytest tests -q
node scripts/validate-readiness-plan.mjs
git diff --check
```

All passed: strict mypy checked 47 source files, 241 backend tests passed with two
existing upstream deprecation warnings, and roadmap validation checked 40 guides
and 573 local links. Fixtures cover exact noncanonical JSON bytes/Unicode, correct
ID/offset control roles, changed IDs with equal counts, bounded canary, partial
transport/deadline/oversized responses, invalid JSON, byte/descriptor/role/page
caps, unsafe/repeated role and wrong endpoint/operation/spatial/time query,
standalone writer byte limits, and observation-specific replay retention.

An initial API-only bind omitted `render.yaml` and caused two blueprint lookup
failures; mounting the full isolated repository resolved both. A temporary
`BinaryIO` yield annotation failed strict typing and was replaced by the bounded
writer interface. No product fallback or assertion was weakened.

## Real API/PostGIS

```text
node scripts/run-integration.mjs --suite api --scenario d01-scoped
```

The clean implementation head passed run `2026-09-27T06-58-18-882Z-cbf9e9f2`,
project `urbanization_t01_04f72b64697e`. [Exact run metadata](B01-control-evidence-run.json)
records the commit, image identities, fixture checksum and successful teardown.
[Sanitized synthetic results](B01-control-evidence-results.json) preserve the
exact generated result bytes (SHA-256
`89698fb1631a7d07bdc734ca20b78c842de2bce70af1ef04da00dc86e2c561ba`).

The local HTTP fixture made eight requests: five complete, three count/ID
mismatch. The scenario reread retained original controls and verified their
bytes/checksums, source/run identities and stable initial/final IDs. The failed
case retained only initial metadata/count/IDs, with no false final proof.
Real public source-health retained its previous complete coverage and success
time while exposing the failed unactivated attempt; that result survived API
restart. Canonical development row hashes stayed identical. Teardown left zero
containers and volumes with this run's exact Compose project label.

No additional official upstream requests, snapshot refresh, public activation,
email or deployment occurred. No migration is needed. Application rollback can
ignore the new staging descriptors while leaving private evidence intact.

The approved roadmap records D01 implementation acceptance from merged PR28+33,
keeps wetlands/county reconciliation, unknown canary coverage and O04 rights as
activation gates, adds B01/B02, and splits P04 into shadow P04a and gated P04b.
B02 remains planned and P04's aggregate completion status remains unchanged.
