# Operations Monitoring

The API exposes two health surfaces with different jobs:

- `GET /health` is a liveness check. Use it for platform health checks that should only confirm
  the API process can respond.
- `GET /health/source-health` is a source freshness check. Use it for uptime/error monitoring once
  ingestion jobs are expected to run.

`/health/source-health` returns `200` when every active configured source has a healthy latest run,
no recorded errors, and a `last_checked_at` value inside the freshness window. It returns `503` when any
active source has never run, reports a failing/degraded status, has validation errors, has an invalid
`last_checked_at` timestamp, or is stale.

The default freshness window is 48 hours. Override it with:

```bash
SOURCE_HEALTH_MAX_AGE_HOURS=72
```

For one-off checks, pass a query parameter:

```bash
curl "https://api.example.test/health/source-health?max_age_hours=72"
```

The response includes per-source issue codes such as `not_run`, `missing_checked_at`,
`status:failing`, `errors:1`, and `stale:49.0h`.
