#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${DATABASE_URL:-}" ]]; then
  echo "DATABASE_URL is required." >&2
  exit 1
fi

backup_dir="${BACKUP_DIR:-backups/postgres}"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "${backup_dir}"

pg_dump --format=custom --no-owner --no-acl "${DATABASE_URL}" \
  > "${backup_dir}/urbanization_tracker_${timestamp}.dump"

echo "${backup_dir}/urbanization_tracker_${timestamp}.dump"
