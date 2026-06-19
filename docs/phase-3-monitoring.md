# Phase 3 Monitoring

Phase 3 adds reviewer-gated public monitoring workflows:

- Huntsville Planning Commission agenda PDF ingestion.
- Stored source documents and extracted text artifacts.
- PDF-derived staged development records.
- Public source submissions.
- Reviewer moderation for submissions and agenda candidates.
- User-defined watch areas.
- Email-ready alert queue records.
- Record version history and a public change log.
- Duplicate candidate signals between staged records and published ArcGIS records.

## Agenda Ingestion

Run:

```bash
make ingest-huntsville-agendas
```

Or directly:

```bash
cd apps/api
. .venv/bin/activate
python -m app.ingestion.cli ingest-huntsville-agendas --data-dir ../../data --document-limit 3
```

Artifacts are written under:

- `data/raw/planning_agendas/`
- `data/processed/source_documents/`
- `data/processed/phase3_source_documents.json`
- `data/processed/phase3_agenda_staged_records.json`
- `data/processed/phase3_duplicate_candidates.json`
- `data/processed/phase3_agenda_health.json`

The current Huntsville archive page is:

https://www.huntsvilleal.gov/planningagendas/

The City site can reject plain Python archive-page requests. The connector first tries the archive
page, then falls back to `curl` archive fetching, then to a short curated list of official current
agenda PDF URLs documented during source review. Direct agenda PDFs are still fetched from the City
site and extracted with PyMuPDF.

The Render Blueprint includes a starter weekday cron job named
`urbanization-tracker-agenda-ingestion`:

```bash
python -m app.ingestion.cli ingest-huntsville-agendas --data-dir /app/data --document-limit 3
```

It runs with `PHASE3_STORE_BACKEND=postgres` so reviewer-facing source documents, staged agenda
records, and agenda health survive ephemeral cron containers. Duplicate-candidate generation still
reads published records from `data_dir/processed/development_records.json`; when
`PROCESSED_STORE_BACKEND=postgres` is used without that artifact file, hosted agenda cron runs may
produce empty or incomplete duplicate candidates until the duplicate lookup is moved to the durable
processed store. Raw PDFs and extracted text under `/app/data/` remain temporary until persistent
disk or object storage is configured.

## API Surface

- `GET /api/source-documents`
- `GET /api/reviewer/staged-records`
- `GET /api/reviewer/duplicate-candidates`
- `GET /api/reviewer/public-submissions`
- `GET /api/reviewer/watch-areas`
- `GET /api/reviewer/alerts`
- `POST /api/reviewer/alerts/send`
- `GET /api/reviewer/decisions/export`
- `POST /api/reviewer/decisions/import`
- `GET /api/reviewer/phase3-store`
- `POST /api/public-submissions`
- `POST /api/watch-areas`
- `GET /api/change-log`
- `GET /api/development-records/{public_id}/versions`

Reviewer routes accept unauthenticated local development traffic unless `REVIEWER_API_TOKEN` is
configured. In production, set that token and put `/review` plus `/api/reviewer/*` behind an edge
access policy such as Cloudflare Access.

By default, Phase 3 collections are stored as `data/processed/phase3_*.json` artifacts. Set
`PHASE3_STORE_BACKEND=postgres` to store the same operational collections in Postgres via
`phase3_collection_items`. Use `make migrate-phase3-postgres` to copy existing local JSON artifacts
into the database before switching a persistent environment.

Inspect the active backend and per-collection migration status with:

```bash
make phase3-store-status
```

In hosted environments, `PHASE3_STORE_BACKEND=postgres` should be treated as the operational default.
Raw agenda PDFs, extracted text, and raw source payloads remain file artifacts for now; database rows
store the reviewer-facing records and links back to those artifacts.

## Alert Scope

Alerts are queued as email-channel records when a saved watch area intersects a matching published
record. Email is only used as an alert contact, not as a user account or login identifier. SMTP
delivery is opt-in with `ALERT_DELIVERY_ENABLED=true` plus SMTP settings. The app stores the
delivery address privately in the Phase 3 store, returns only the hash/hint through reviewer APIs,
and includes an unsubscribe token for each watch area.

Run a delivery pass with:

```bash
make send-alerts
```

Delivery is rate-limited by `ALERT_DELIVERY_RATE_LIMIT` per run, or by the reviewer-supplied
`limit` when using the reviewer UI/API. Unsubscribe links call
`GET /api/watch-areas/unsubscribe/{token}` and suppress future queued deliveries for that watch.

## Review Rules

PDF-derived and public-submitted records stay pending until a reviewer approves them. A reviewer
should confirm the source document, parse confidence, development status, duplicate candidates, and
geometry before publishing.

The reviewer UI exposes decision export/import for small handoffs and backups. Imported decisions
apply to staged record IDs and report any missing IDs so reviewers can spot stale handoff files.
