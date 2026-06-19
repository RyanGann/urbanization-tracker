from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.alert_delivery import send_queued_email_alerts
from app.config import get_settings
from app.deployment_preflight import run_deployment_preflight
from app.ingestion.agenda_pipeline import ingest_huntsville_agendas
from app.ingestion.pipeline import ingest_huntsville, ingest_madison_county
from app.phase3_store import migrate_artifact_collections_to_postgres, phase3_store_status
from app.processed_store import (
    migrate_processed_artifacts_to_postgres,
    processed_store_status,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Urbanization Tracker ingestion commands")
    subparsers = parser.add_subparsers(dest="command", required=True)

    huntsville = subparsers.add_parser(
        "ingest-huntsville",
        help="Fetch Huntsville New Subdivisions, Building Permits, and selected context layers.",
    )
    huntsville.add_argument(
        "--data-dir",
        type=Path,
        default=get_settings().ingestion_data_dir,
        help="Directory for raw, processed, and run health artifacts.",
    )
    huntsville.add_argument(
        "--permit-limit",
        type=int,
        default=500,
        help="Maximum recent building permits to fetch for point context.",
    )
    huntsville.add_argument(
        "--context-limit",
        type=int,
        default=2000,
        help="Maximum features per environmental context layer.",
    )
    agendas = subparsers.add_parser(
        "ingest-huntsville-agendas",
        help="Fetch Huntsville Planning Commission agenda PDFs into reviewer-gated records.",
    )
    agendas.add_argument(
        "--data-dir",
        type=Path,
        default=get_settings().ingestion_data_dir,
        help="Directory for raw, processed, and run health artifacts.",
    )
    agendas.add_argument(
        "--document-limit",
        type=int,
        default=3,
        help="Maximum agenda PDFs to fetch from the archive page.",
    )
    madison_county = subparsers.add_parser(
        "ingest-madison-county",
        help="Fetch Madison County recorded subdivision polygons.",
    )
    madison_county.add_argument(
        "--data-dir",
        type=Path,
        default=get_settings().ingestion_data_dir,
        help="Directory for raw, processed, and run health artifacts.",
    )
    madison_county.add_argument(
        "--record-limit",
        type=int,
        default=500,
        help="Maximum subdivision polygons to fetch.",
    )
    subparsers.add_parser(
        "migrate-phase3-artifacts-to-postgres",
        help="Copy existing Phase 3 JSON collection artifacts into the Postgres store.",
    )
    subparsers.add_parser(
        "migrate-processed-artifacts-to-postgres",
        help="Copy canonical processed ingestion JSON artifacts into the Postgres store.",
    )
    subparsers.add_parser(
        "processed-store-status",
        help="Report canonical processed ingestion collection counts by backend.",
    )
    subparsers.add_parser(
        "phase3-store-status",
        help="Report Phase 3 operational collection counts for artifact and Postgres stores.",
    )
    send_alerts = subparsers.add_parser(
        "send-alerts",
        help="Deliver queued email alerts through the configured SMTP provider.",
    )
    send_alerts.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum queued alerts to send in this run.",
    )
    deployment_preflight = subparsers.add_parser(
        "deployment-preflight",
        help="Validate production launch configuration and PostGIS readiness.",
    )
    deployment_preflight.add_argument(
        "--skip-database",
        action="store_true",
        help="Skip live database connectivity and PostGIS checks.",
    )

    args = parser.parse_args()
    if args.command == "ingest-huntsville":
        result = ingest_huntsville(
            data_dir=args.data_dir,
            permit_limit=args.permit_limit,
            context_limit=args.context_limit,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
    elif args.command == "ingest-huntsville-agendas":
        result = ingest_huntsville_agendas(
            data_dir=args.data_dir,
            document_limit=args.document_limit,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
    elif args.command == "ingest-madison-county":
        result = ingest_madison_county(
            data_dir=args.data_dir,
            record_limit=args.record_limit,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
    elif args.command == "migrate-phase3-artifacts-to-postgres":
        result = migrate_artifact_collections_to_postgres()
        print(json.dumps(result, indent=2, sort_keys=True))
    elif args.command == "migrate-processed-artifacts-to-postgres":
        result = migrate_processed_artifacts_to_postgres()
        print(json.dumps(result, indent=2, sort_keys=True))
    elif args.command == "processed-store-status":
        result = processed_store_status()
        print(json.dumps(result, indent=2, sort_keys=True))
    elif args.command == "phase3-store-status":
        result = phase3_store_status()
        print(json.dumps(result, indent=2, sort_keys=True))
    elif args.command == "send-alerts":
        result = send_queued_email_alerts(limit=args.limit)
        print(json.dumps(result, indent=2, sort_keys=True))
    elif args.command == "deployment-preflight":
        result = run_deployment_preflight(check_database=not args.skip_database)
        print(json.dumps(result, indent=2, sort_keys=True))
        if result["status"] == "fail":
            raise SystemExit(1)


if __name__ == "__main__":
    main()
