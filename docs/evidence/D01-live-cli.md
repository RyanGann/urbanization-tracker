# D01 bounded live Python CLI verification

On 2026-09-27 UTC, the actual Python staging CLI ran against all five current
official connectors at code SHA `7e6a40c23ffd0d6c2f2d7fc01d34cec3c21e1ad7`.
This closes the previously unrun live-command acceptance item. It does not
establish upstream completeness, redistribution permission, or activation.

The existing installed-dependency image was
`sha256:65e132c26c6eaacffd8fdaf138d3fc4d274de896db0a8bec22ac64be9d5424af`.
A one-shot `docker run --rm` mounted the isolated checkout's `apps/api` read-only
at `/app`, the exact previously reviewed local scope read-only at
`/scope/reviewed.json`, and a fresh ignored output directory at `/output`.
No Docker services or databases were started or changed.

```text
python -m app.ingestion.cli stage-scoped-arcgis --scope-file /scope/reviewed.json --output-dir /output --canary
```

The scope file SHA-256 was
`a8b087c77c27fe8cc84a08b09ba946edcdd4f1a1463e5c68ee2e81cf0d4dd825`.
Its review timestamp remains `2026-09-24T04:43:51.111Z`; no boundary was refreshed.
Boundary/context digests and sanitized per-request method, endpoint, status,
query digest, and response bytes are in [the report](D01-live-cli-20260927.json).
The bundle is an array containing each exact generated canonical JSON report
on its own line. To reproduce a source report digest, remove the array separator
comma from its line (if present), append one LF byte, and hash those UTF-8 bytes.
No JSON reserialization is needed; it could alter numeric spelling.

| Source | Original report SHA-256 |
| --- | --- |
| Building permits | `a802a1adb4d48e8050dea3bd511a8b7d62ee600d7ca3c5be078da539099fb7e9` |
| FEMA 1% floodplain | `fbfcfe667b388e4a505a9cf4bfbec47a262a8a817ae2ac46c5cd79cf4aa9a67a` |
| New subdivisions | `c746132af9f55d43439c84602a2daa9c717c5d9cfdbdff9624c80aa70edb7dbe` |
| USFWS wetlands | `9ce0990e46329fbf0bbe2012101a43543eae6566b8f746f18c641d6e7a7bef48` |
| County subdivisions | `01dac99e959da58a1725bfa917fd2dd170c0fa745ffc5c69e9bf51f823a747ce` |

Full scope geometry and sampled pages remain ignored locally at
`tmp/d01-live-cli-20260927/` in the isolated worktree.

| Source | Requests | Bytes | Scoped count | Accepted sample | Result |
| --- | ---: | ---: | ---: | ---: | --- |
| Building permits | 4 | 140,984 | 17,902 | 25 | unknown coverage, canary |
| FEMA 1% floodplain | 4 | 1,062,946 | 1,210 | 25 | unknown coverage, canary |
| New subdivisions | 4 | 87,145 | 343 | 25 | unknown coverage, canary |
| USFWS wetlands | 3 | 23,704 | 2,499 | 0 | count_id_mismatch, failed |
| County subdivisions | 3 | 39,306 | 4,718 | 0 | count_id_mismatch, failed |

Exit status was **1**, correctly reporting the two count/ID failures. All 18
responses were HTTP 200; there were zero retries and zero rejected sample
features. The total was 1,354,085 received bytes. At most one geometry batch
of 25 features was fetched per source; mismatched sources stopped before geometry.
The unchanged discrepancies were also observed in the previous direct HTTPS
diagnostic. This run's sanitized reports do not retain complete upstream ID sets,
so they do not independently establish the mismatched ID totals or their cause.
No collector correctness change was justified by these observations.

The canary enforces four requests per source, one attempt per request, at least
one second between requests/sources, 20-second request and 5-second connection
timeouts. Existing guards also cap each response at 32 MiB, ID responses at
8 MiB/100,000 IDs, received bytes at 1 GiB per source, and elapsed collection
time at 600 seconds per source. This run remained below every cap.
Neither `--record-attempt` nor any publication/activation path was invoked.

Validation for this evidence-only change: `node scripts/validate-readiness-plan.mjs`
and `git diff --check`. Existing synthetic real API/PostGIS evidence remains in
[D01-scoped-ingestion.md](D01-scoped-ingestion.md); no new real-stack or unit-test
claims are made here. No schema, migration, or runtime behavior changed.
