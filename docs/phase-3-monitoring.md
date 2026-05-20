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

## API Surface

- `GET /api/source-documents`
- `GET /api/reviewer/staged-records`
- `GET /api/reviewer/duplicate-candidates`
- `POST /api/public-submissions`
- `GET /api/public-submissions`
- `GET /api/watch-areas`
- `POST /api/watch-areas`
- `GET /api/alerts`
- `GET /api/change-log`
- `GET /api/development-records/{public_id}/versions`

## Alert Scope

Alerts are queued as email-channel records when a saved watch area intersects a matching published
record. SMTP delivery is intentionally not configured in this local MVP; the queue is the durable
handoff point for a later mail worker.

## Review Rules

PDF-derived and public-submitted records stay pending until a reviewer approves them. A reviewer
should confirm the source document, parse confidence, development status, duplicate candidates, and
geometry before publishing.
