#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "Run this script as root: wsl -u root -- bash scripts/wsl/setup_services.sh" >&2
  exit 1
fi

: "${MARIADB_ADMIN_USER:=root}"

prompt_secret() {
  local variable=$1
  local label=$2
  if [[ -z ${!variable:-} ]]; then
    if [[ ! -t 0 ]]; then
      echo "Set ${variable}, or run this script from an interactive WSL terminal." >&2
      exit 1
    fi
    read -r -s -p "${label}: " "${variable}"
    echo
    export "${variable}"
  fi
}

prompt_secret NEUROTECH_DB_DEV_PASSWORD "Password matching DATABASE_URL for neurotech_dev"
prompt_secret NEUROTECH_DB_TEST_PASSWORD "Password matching TEST_DATABASE_URL for neurotech_test"

password_pattern='^[A-Za-z0-9_.-]{12,128}$'
if [[ ! ${NEUROTECH_DB_DEV_PASSWORD} =~ ${password_pattern} ]] ||
   [[ ! ${NEUROTECH_DB_TEST_PASSWORD} =~ ${password_pattern} ]]; then
  echo "Database passwords must be 12-128 characters using letters, digits, dot, dash or underscore." >&2
  exit 1
fi

missing=()
command -v mariadb >/dev/null 2>&1 || missing+=(mariadb-server)
command -v redis-server >/dev/null 2>&1 || missing+=(redis-server)
if ((${#missing[@]})); then
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y "${missing[@]}"
fi

install -d -m 0755 /etc/mysql/mariadb.conf.d
install -d -m 0755 /etc/redis

cat >/etc/mysql/mariadb.conf.d/99-neurotech-local.cnf <<'EOF'
[mysqld]
bind-address = 127.0.0.1
character-set-server = utf8mb4
collation-server = utf8mb4_unicode_ci
skip-name-resolve = 1
EOF

if [[ -f /etc/redis/redis.conf ]]; then
  sed -i -E 's/^bind .*/bind 127.0.0.1 ::1/' /etc/redis/redis.conf
  sed -i -E 's/^protected-mode .*/protected-mode yes/' /etc/redis/redis.conf
fi

systemctl enable --now mariadb redis-server
systemctl restart mariadb redis-server

admin_args=(--user="${MARIADB_ADMIN_USER}")
if [[ -n ${MARIADB_ADMIN_PASSWORD:-} ]]; then
  export MYSQL_PWD="${MARIADB_ADMIN_PASSWORD}"
elif ! mariadb "${admin_args[@]}" -N -e "SELECT 1" >/dev/null 2>&1; then
  prompt_secret MARIADB_ADMIN_PASSWORD "Existing MariaDB ${MARIADB_ADMIN_USER} password"
  export MYSQL_PWD="${MARIADB_ADMIN_PASSWORD}"
fi

mariadb "${admin_args[@]}" <<SQL
CREATE DATABASE IF NOT EXISTS neurotech_dev CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS neurotech_test CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS 'neurotech_dev'@'%' IDENTIFIED BY '${NEUROTECH_DB_DEV_PASSWORD}';
ALTER USER 'neurotech_dev'@'%' IDENTIFIED BY '${NEUROTECH_DB_DEV_PASSWORD}';
CREATE USER IF NOT EXISTS 'neurotech_test'@'%' IDENTIFIED BY '${NEUROTECH_DB_TEST_PASSWORD}';
ALTER USER 'neurotech_test'@'%' IDENTIFIED BY '${NEUROTECH_DB_TEST_PASSWORD}';
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, DROP, INDEX, ALTER, REFERENCES
  ON neurotech_dev.* TO 'neurotech_dev'@'%';
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, DROP, INDEX, ALTER, REFERENCES
  ON neurotech_test.* TO 'neurotech_test'@'%';
FLUSH PRIVILEGES;
SQL

redis-cli ping >/dev/null
mariadb "${admin_args[@]}" -N -e "SELECT 1" >/dev/null
unset MYSQL_PWD || true
echo "NeuroTech MariaDB and Redis services are ready on WSL2 localhost."
