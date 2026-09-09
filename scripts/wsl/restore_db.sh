#!/usr/bin/env bash
set -euo pipefail

if (($# < 1)); then
  echo "Usage: restore_db.sh <backup.sql.gz> [database] [user]" >&2
  exit 1
fi
if [[ -z ${NEUROTECH_DB_PASSWORD:-} ]]; then
  if [[ ! -t 0 ]]; then
    echo "Set NEUROTECH_DB_PASSWORD for a non-interactive restore." >&2
    exit 1
  fi
  read -r -s -p "MariaDB password for the restore user: " NEUROTECH_DB_PASSWORD
  echo
fi
backup=$1
database=${2:-neurotech_dev}
user=${3:-neurotech_dev}
test -f "${backup}"
gzip -dc -- "${backup}" | MYSQL_PWD=${NEUROTECH_DB_PASSWORD} mariadb \
  --host=127.0.0.1 --user="${user}" "${database}"
unset NEUROTECH_DB_PASSWORD || true
echo "Restored ${database} from ${backup}."
