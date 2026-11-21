#!/usr/bin/env bash
set -Eeuo pipefail

cd "$(dirname "$0")/.."

export APP_ENV="${APP_ENV:-production}"
[ -f .env ] && { set -a; . ./.env; set +a; }
[ -f ".env.${APP_ENV}" ] && { set -a; . ".env.${APP_ENV}"; set +a; }

: "${DB_USER:?DB_USER is not set}"
: "${DB_NAME:?DB_NAME is not set}"

BACKUP_DIR="./data/backups"
mkdir -p "${BACKUP_DIR}"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/${DB_NAME}_${TIMESTAMP}.dump"
TMP_FILE="${BACKUP_FILE}.part"
trap 'rm -f "${TMP_FILE}"' EXIT

# streaming dump directly to host filesystem
./scripts/cc.sh exec -T postgres pg_dump -U "${DB_USER}" "${DB_NAME}" -Fc > "${TMP_FILE}"
if [[ ! -s "${TMP_FILE}" ]]; then
  echo "[backup] FATAL: empty dump produced" >&2
  exit 1
fi
mv -f "${TMP_FILE}" "${BACKUP_FILE}"

# keep only last 14 days
find "${BACKUP_DIR}" -type f -name "${DB_NAME}_*.dump" -mtime +14 -delete