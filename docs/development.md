# NeuroTech backend development

## Architecture

Flask and the Vue application run on Windows. MariaDB and Redis run as `systemd`
services inside WSL2 and are reachable only through WSL localhost forwarding.
Service data must remain in the Linux filesystem (the distro defaults), never
under `/mnt/c` or `/mnt/d`.

Application code follows `routes → services → domain`; SQLAlchemy, Redis, email,
SMS, and payment implementations live in `app/core` as adapters.

## First setup

From an Ubuntu 24.04 WSL shell, run the idempotent installer. It prompts securely
for the two application passwords and, only when passwordless MariaDB root access
is unavailable, the existing MariaDB administrator password:

```bash
sudo bash scripts/wsl/setup_services.sh
```

The script installs and enables MariaDB and Redis, binds both to loopback, and
creates separate limited users/databases for `neurotech_dev` and `neurotech_test`.
Enter the same development/test passwords used in the URL-encoded `.env`
connection strings. The input is hidden and is not written to shell history.
Do not commit any of these values.
Copy `.env.example` to `.env` on Windows and replace every placeholder secret.

Then, from PowerShell in the backend repository:

```powershell
.venv\Scripts\python.exe -m pip install -e ".[dev]"
.venv\Scripts\python.exe -m alembic upgrade head
.venv\Scripts\python.exe -m flask --app app:create_app seed
.venv\Scripts\python.exe -m flask --app app:create_app bootstrap-admin
.venv\Scripts\python.exe -m flask --app app:create_app run
```

`bootstrap-admin` works only while no admin exists. Every later `specialist` or
`admin` account must be created through an invitation from an authenticated admin.

Run the frontend separately with `npm run dev`. Its default API URL is
`http://127.0.0.1:5000/api/v1`; override it with `VITE_API_BASE_URL` when needed.

## Verification

```powershell
scripts\wsl\test_connections.ps1
.venv\Scripts\python.exe -m ruff check .
.venv\Scripts\python.exe -m pytest --cov-report=json:.coverage-report.json
.venv\Scripts\python.exe scripts\check_layer_coverage.py
```

The test suite enforces at least 85% overall coverage. The second check enforces
at least 95% branch coverage across `app/domain` and `app/services`.

`GET /api/v1/health/live` checks the process. `GET /api/v1/health/ready` checks
both MariaDB and Redis. Swagger UI is available at `/api/v1/docs` only in
development and testing.

## Database lifecycle

Migrations contain schema changes; seed data stays in the separate idempotent
`flask seed` command. Never connect the backend as MariaDB root.

Create a development backup from WSL:

```bash
bash scripts/wsl/backup_db.sh
```

Restore into the development database and validate it:

```bash
bash scripts/wsl/restore_db.sh path/to/backup.sql.gz
```

Prefer the non-destructive verification command before a real restore. It loads
the dump into a fixed temporary database and removes that database afterward:

```bash
bash scripts/wsl/verify_restore.sh path/to/backup.sql.gz
```

The backup, restore, and verification scripts prompt for passwords with hidden
input. For automation, provide the documented password environment variable
through the runner's secret store rather than placing it in the command line.

The scripts reject unsupported targets and keep backup artifacts outside source
control. Test restores before relying on a backup.

## Security model

- JWT access and refresh tokens are HttpOnly cookies; JavaScript only reads the
  separate CSRF cookies and sends `X-CSRF-TOKEN`.
- Access tokens last 15 minutes, refresh tokens 7 days, and sessions at most 30 days.
- Refresh rotation and revocation state are persisted in MariaDB.
- OTP values are hashed in Redis, expire after five minutes, and are never logged.
- If Redis is unavailable, limited Auth operations fail closed with HTTP 503.
- The fake SMS, email, and payment adapters are development/testing facilities only.
