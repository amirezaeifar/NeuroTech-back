#!/usr/bin/env bash
set -euo pipefail

if (($# != 1)); then
  echo "Usage: verify_restore.sh <backup.sql.gz>" >&2
  exit 1
fi
: "${MARIADB_ADMIN_USER:=root}"
backup=$1
test -f "${backup}"
database=neurotech_restore_check
admin_args=(--host=127.0.0.1 --user="${MARIADB_ADMIN_USER}")
if [[ -z ${MARIADB_ADMIN_PASSWORD:-} ]]; then
  if [[ ! -t 0 ]]; then
    echo "Set MARIADB_ADMIN_PASSWORD for non-interactive restore verification." >&2
    exit 1
  fi
  read -r -s -p "MariaDB password for ${MARIADB_ADMIN_USER}: " MARIADB_ADMIN_PASSWORD
  echo
fi
export MYSQL_PWD="${MARIADB_ADMIN_PASSWORD}"

cleanup() {
  mariadb "${admin_args[@]}" -e "DROP DATABASE IF EXISTS ${database}" >/dev/null
  unset MYSQL_PWD || true
}
trap cleanup EXIT

mariadb "${admin_args[@]}" -e \
  "DROP DATABASE IF EXISTS ${database}; CREATE DATABASE ${database} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
gzip -dc -- "${backup}" | mariadb "${admin_args[@]}" "${database}"
table_count=$(mariadb "${admin_args[@]}" -N -e \
  "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='${database}'")
if ((table_count == 0)); then
  echo "Restore verification failed: no tables were restored." >&2
  exit 1
fi
echo "Restore verified successfully (${table_count} tables); temporary database removed."
