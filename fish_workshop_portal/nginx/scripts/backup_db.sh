#!/usr/bin/env bash
set -Eeuo pipefail

cd "$(dirname "$0")/.."

APP_ENV="${APP_ENV:-production}"
[ -f .env ] && { set -a; . ./.env; set +a; }
[ -f ".env.${APP_ENV}" ] && { set -a; . ".env.${APP_ENV}"; set +a; }

: "${DB_USER:?DB_USER is not set}"
: "${DB_NAME:?DB_NAME is not set}"

BACKUP_DIR="./data/backups"
mkdir -p "${BACKUP_DIR}"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/${DB_NAME}_${TIMESTAMP}.dump"

# streaming dump directly to host filesystem
docker compose exec -T postgres pg_dump -U "${DB_USER}" "${DB_NAME}" -Fc > "${BACKUP_FILE}"

# keep only last 14 days
find "${BACKUP_DIR}" -type f -name "${DB_NAME}_*.dump" -mtime +14 -delete