# C02 transactional creation evidence

The tested C02 code candidate is `6d04d997e111cabf2170cc3d3850b06f8985fa7e`.
It uses one PostgreSQL transaction and advisory lock `(2088694651, 1)` for the
public-submission and watch-area creation paths. The follow-on evidence and CI
wiring commit does not change that application behavior.

## Merged verification

[PR #21](https://github.com/RyanGann/urbanization-tracker/pull/21) merged as
`54f6c57b7a581c258aafe95026f46d852e83c85f` after lead acceptance, a completed
Codex review with no findings or open threads, and successful
[CI run 35488936703](https://github.com/RyanGann/urbanization-tracker/actions/runs/35488936703).
The reviewed and tested PR head was `1fc4fff8d0044da8b26dfc86a2caebcc48077934`.
CI included the ordinary API/web checks and the P01, T01, C01, and C02 real-stack
scenarios. The merge used that expected head SHA.

## Real stack

Command:

```text
node scripts/run-integration.mjs --suite concurrency
```

The final code-candidate run passed on September 20, 2026. Its isolated project was
`urbanization_t01_1f145f365332`; its ignored local manifest is
`tmp/integration/2026-09-20T04-18-24-468Z-e8f9a23f/manifest.json` and records
`outcome: passed` and `cleanup_result: removed`. It records base commit
`f03764fcd63a1fdaadfdb9a700db2f8f11488d1b`, `working_tree_dirty: true`; the
working-tree changes exercised by the run were immediately committed as
`6d04d997e111cabf2170cc3d3850b06f8985fa7e`. Fixture SHA-256:
`932eacb03655a3dee1a2838abf9ddf8d5dfa44f744482408611b61a2561bbee2`.
Its token-free scenario result at
`tmp/integration/2026-09-20T04-18-24-468Z-e8f9a23f/c02-data/results.json`
records the exact checks and generated receipt identifiers.

The scenario synchronizes two real HTTP requests before they attempt the lock.
It verifies both submission receipts and staged rows, both watch receipts and
their initial alerts, and all four groups after an API restart. It also proves
that an injected failure after a staged write leaves neither receipt nor staged
row, and that a failure after watch alerts leaves neither watch nor alert.
Holding the same real advisory lock returns a bounded, token-free 503 from a
mutation while an unrelated read remains available; creation succeeds after the
lock releases. Finally, the production `SessionLocal(autoflush=False)` performs
three real PostgreSQL item writes: a repeated item upsert leaves one updated row
and preserves the sibling row's order.

## Ordinary checks

A clean Python 3.12 container copied and installed the current API source using
the locked dependencies. Ruff formatting/checking, mypy (32 source files), and
31 focused API tests passed. `node --check scripts/run-integration.mjs` and
`git diff --check` also passed. The concurrency scenario is a required CI step;
CI uploads its isolated artifacts even on failure.

## Scope limit

The remaining legacy writers in [the C02 inventory](C02-writer-inventory.md)
are explicitly **not** concurrency-safe. Artifact and demo modes use atomic
replacement per JSON file only; they are documented single-writer modes and do
not provide cross-file transactions. Network, upload, PDF, and SMTP work stays
outside the PostgreSQL transaction and lock.
