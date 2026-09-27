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

## Reviewed request-binding correction

Codex found that redirect-following could mislabel bytes with the original
endpoint/query. Every scoped GET/POST now explicitly disables redirects, including
injected clients configured to follow them; redirect status/history fails before
control capture. The actual response request's method/endpoint and decoded GET
query or POST form must match the trusted intended request exactly. Extra/default
URL parameters, changed selectors and duplicate keys refuse proof. POST URL query
parameters are refused, since the scoped query belongs to the form body.

The final runtime head `8243fab46ab145646161c39aadda532cdff6b2db` passed backend
lint, strict types (47 files) and 252 tests, including GET/POST foreign-host redirects
with both client redirect settings (one actual request, zero controls), built-in
client policy, hidden default time/version params and duplicate actual query keys.

The same clean head passed real run `2026-09-27T07-10-03-821Z-cade0e29` with the
same exact command above. [Final run metadata](B01-control-evidence-final-run.json)
and [final synthetic results](B01-control-evidence-final-results.json) record the
successful byte/hash/source/run checks, health/restart/canonical preservation and
teardown. Final result bytes SHA-256:
`b65f827e1b09e45ab5465dccd77d5b6591b9e3a0c85b610254575a7bd3c25333`.
Project `urbanization_t01_8eeb877286dc` left zero labelled containers/volumes.
No official source requests were made during either fixture run.

## Final authority and form binding

The final runtime head `90571c8d8c6f72682d760a0a840a3b537fa9c3e7` also binds
the actual request's single Host header to its normalized URL authority, including
explicit/default port consistency. POST requires one form Content-Type with only
an optional UTF-8 charset and absent or identity Content-Encoding. Injected
headers/hooks, duplicate authorities/media types and encoded bodies fail before
control capture. Ruff, strict mypy (47 files) and all 274 backend tests passed.

That clean head passed run `2026-09-27T07-25-56-928Z-7e55e337` using the same
command above. [Authority run metadata](B01-control-evidence-authority-run.json)
and [exact synthetic results](B01-control-evidence-authority-results.json) preserve
the successful checks; result SHA-256 is
`50e392e65fa03c7bfce139bc40368b7f88c54cbb5b9cc3a10d3a986fe5dd9a6c`.
Independent exact-label queries confirmed zero containers and volumes for
`urbanization_t01_56595c296b2c`. The CI workflow now runs the owning `d01-scoped`
scenario to exercise original controls and request binding on future changes.
No official source requests were made.

## Hook-free injected client contract

A subsequent review identified that response hooks can rewrite `response.request`
before identity validation, and request hooks can install such response hooks.
Injected clients with either hook type are now refused before each send, returning
`source_client_hooks_refused` with zero requests and no finalized controls. The
production default client is unchanged. Test transport injection supplies fixture
bytes; arbitrary Python transports are not a claim of server authenticity.
Injected clients must also have `auth=None`: HTTPX auth generators can mutate
then restore the request just like hooks. Both unsupported configurations are
checked before every send and refuse proof without I/O.
Static Authorization/Proxy-Authorization/Cookie headers and nonempty cookie jars
are also refused before each send, with defensive actual-header validation before
capture. Thus retained observations describe the supported unauthenticated public
request context. These checks do not provide an upstream cryptographic signature.
The clean `90571c8` real run above predates this unsupported-client guard. The
owning CI scenario checks the current default-client path.

Repeated collection now exclusively creates a fresh source destination. Existing
directories (including empty ones) return `stage_destination_exists` with zero
requests and no writes; prior reports, pages and controls remain byte-identical.
This avoids orphaning older control files behind an overwritten report and gives
one bounded observation per destination. Operators choose a fresh output root for
each invocation; archival/retention of separate runs remains an operator policy.
The scoped suite passes 103 tests, Ruff and strict mypy (55 current source files).
