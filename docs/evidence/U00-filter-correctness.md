# U00 filter correctness evidence

## Merged verification

[PR #20](https://github.com/RyanGann/urbanization-tracker/pull/20) merged as `fbd5ad8a5e6d4af474d7eb07a4abbcb8b655c046`. Codex completed a clean review of final head `3468b8c67f1f93534af602d57932c6beb33cc309`; no review threads remained open. [CI run 35489697612](https://github.com/RyanGann/urbanization-tracker/actions/runs/35489697612) passed on that head, including the ordinary checks and isolated integration scenarios. The local evidence below retains its original run SHA and limitations.

This change verifies that the map list, GeoJSON query, and selection state use the same filter semantics against the real PostGIS-backed API. The fixture is deterministic and contains three published records: one completed subdivision and two public submissions (one proposed and one final).

## Reproduction

From the repository root, with Node 22+, Docker Compose, and the checked-in lockfiles:

```text
node scripts/run-integration.mjs --suite live --scenario u00-filters
```

The scenario is opt-in. The default live suite keeps the U00 browser spec ignored/skipped and continues to exercise the existing T01 fixture. The dedicated runner sets `U00_FILTERS=1` only for the U00 browser container.

## Final real-stack run

The final run used commit `2c046069eda84d185b2812ea13bbcd33441453f9` after rebasing onto merged main, fixture SHA-256 `eb691061161198eac289b85693ae951e46767d432f193aba7605447a59597527`, and Docker images recorded in the manifest.

Artifact directory:

```text
tmp/integration/2026-09-20T04-32-44-957Z-eb0e0e40/
```

The manifest reports `outcome: passed`, `working_tree_dirty: false`, and cleanup `removed`. The API driver ran before and after an API restart and required the same results in both phases:

- unfiltered list and GeoJSON contained the same three fixture IDs;
- completed status returned only `u00-completed-development` in both representations;
- `public_submission` returned the two submission records in both representations;
- explicit `status=none`, `confidence=none`, and `flag=none` each returned zero records in both representations;
- mixed `none` plus a value and an unknown confidence returned HTTP 422 with `code: invalid_filter`.

The Chromium test result is `playwright/live.junit.xml`: one test, zero failures, zero skips. It physically exercised the shipped UI by narrowing the flag selection and using the local **Clear flag restriction** action, deselecting all development types and resetting them, deselecting all statuses and observing zero results, selecting the proposed submission, then changing status/type filters and verifying the selected detail cleared when the record left the result set.

## Focused checks

These checks passed on the final branch:

```text
npm run test:web       # 1 file, 6 tests passed
npm run typecheck:web  # passed
npm run build:web      # passed; MapLibre worker 509.18 kB
git diff --check       # passed
```

The existing API focused suite and the prior green CI run cover the backend parser and list/GeoJSON unit paths. The full API suite, default T01 live smoke, C01/C02 scenarios, and the hosted CI matrix were not rerun locally after the final rebase; the workflow keeps their existing steps and adds the dedicated U00 command above.

The fixture and browser artifacts are intentionally kept under ignored `tmp/integration`; this tracked document records the reproducible command and exact result paths without committing generated service logs or private runtime data.
