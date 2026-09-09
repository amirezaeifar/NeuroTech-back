#!/usr/bin/env bash
set -euo pipefail

if [[ -z ${NEUROTECH_DB_PASSWORD:-} ]]; then
  if [[ ! -t 0 ]]; then
    echo "Set NEUROTECH_DB_PASSWORD for a non-interactive backup." >&2
    exit 1
  fi
  read -r -s -p "MariaDB password for the backup user: " NEUROTECH_DB_PASSWORD
  echo
fi
database=${1:-neurotech_dev}
user=${2:-neurotech_dev}
destination=${3:-"$HOME/neurotech-backups"}
mkdir -p -- "${destination}"
stamp=$(date -u +%Y%m%dT%H%M%SZ)
output="${destination}/${database}-${stamp}.sql.gz"
MYSQL_PWD=${NEUROTECH_DB_PASSWORD} mariadb-dump \
  --host=127.0.0.1 --user="${user}" --single-transaction --skip-lock-tables \
  "${database}" | gzip -9 >"${output}"
unset NEUROTECH_DB_PASSWORD || true
echo "${output}"
