# C02 writer inventory

This inventory records the remaining mutable paths after C02 moves public
submission and watch creation to item-level PostgreSQL mutations. The pilot
advisory lock is not a claim that these unmigrated paths are concurrency-safe.

| Writer or call chain | Current mutation surface | Owner for migration |
| --- | --- | --- |
| `POST /api/public-submissions` → `create_public_submission` | `public_submissions`, `submission_staged_records`, `duplicate_candidates` | **C02** |
| `POST /api/watch-areas` → `create_watch_area` | `watch_areas`, `alerts` | **C02** |
| Ingestion pipeline → `write_processed_list` / `write_processed_payload` | processed canonical collections; legacy full replacement | C03 source merges |
| P02 compact `map_layer_catalog` singleton | processed `latest` singleton; legacy file/table replacement | C03 source merges |
| Agenda import → `replace_agenda_artifacts` | source documents, agenda staged records, candidates, health | C04 agenda merges |
| Reviewer decisions/export-import and submission status mutations | staged and public-submission operational collections | C05 review/import actions |
| Reviewer publish path → `publish_phase3_staged_record` | staged records, development records, versions, change log | C06 publication |
| Initial/future match generation | watch areas and alerts | C07 matcher |
| Delivery result mutation → `mark_alert_delivery_result` | alerts | C08 sender |
| Unsubscribe/confirmation lifecycle | watch areas and token state | S03 subscription lifecycle |
| Duplicate merge | canonical IDs, aliases, history and candidates | C09 merge |
| Artifact-to-PostgreSQL migration helpers | explicit maintenance import; legacy full replacement | C03/C04 by source collection |

Artifact and demo storage remain explicit single-writer development modes. C02
uses atomic replacement for each artifact file, but cannot make a multi-file
mutation atomic. Network fetches, uploads, PDF processing and SMTP stay outside
the PostgreSQL transaction and advisory lock.
