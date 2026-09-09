# NeuroTech Backend

Backend API for the NeuroTech platform, built with Python and Flask using a
Semi-Clean modular monolith architecture.

The current MVP includes MariaDB migrations, Redis-backed OTP and rate limiting,
JWT cookie authentication, role checks, the Academy catalogue, enrollments,
lesson progress, moderated comments, orders, and an idempotent development
payment gateway. HTTP errors use RFC 9457 Problem Details.

See [the development guide](docs/development.md) for the WSL2 service setup,
migrations, seed data, health checks, backup, and restore workflow.

## Architecture

The codebase keeps business rules independent from Flask, SQLAlchemy, and
external providers.

```text
app/
├── bootstrap.py  # Composition root; wires implementations to interfaces
├── core/         # Configuration, database adapters, integrations, and storage
├── domain/       # Entities, value objects, business rules, and interfaces
├── services/     # Use cases and transaction orchestration
└── routes/       # HTTP routes and request/response schemas
```

Dependency direction:

```text
routes → services → domain
core ────────────→ domain
bootstrap wires routes, services, and core together
```

Rules:

- `domain` does not import Flask, SQLAlchemy, MariaDB, or provider SDKs.
- `routes` parse HTTP input and call services; they do not query the database.
- `services` coordinate use cases and transaction boundaries.
- `core` contains technical implementations of domain interfaces.
- `bootstrap.py` wires dependencies and contains no business rules.

## Current structure

```text
NeuroTech-back/
├── app/
│   ├── __init__.py
│   ├── bootstrap.py
│   ├── core/
│   ├── domain/
│   ├── routes/
│   └── services/
├── storage/
│   └── uploads/
├── tests/
│   ├── api/
│   ├── integration/
│   └── unit/
├── .env.example
├── .gitignore
├── pyproject.toml
└── README.md
```

## Prerequisites

- Python 3.11 or newer
- A virtual environment tool available with Python
- WSL2 with `systemd`, MariaDB, and Redis for normal development/integration tests

## Quick start

From the repository root, create and activate a virtual environment.

### Windows PowerShell

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

### macOS or Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env
```

Run the development server:

```powershell
flask --app app run --debug
```

Verify the API:

```powershell
Invoke-RestMethod http://127.0.0.1:5000/api/v1/health
```

Expected response:

```json
{
  "service": "neurotech-api",
  "status": "healthy",
  "version": "0.1.0"
}
```

## HTTP contract

All current and future API routes are versioned under `/api/v1`. Every response
contains an `X-Request-ID` header so an individual request can be correlated
with server logs.

Expected API errors use `application/problem+json` and follow RFC 9457:

```json
{
  "type": "https://api.neurotech.local/problems/not-found",
  "title": "Not Found",
  "status": 404,
  "detail": "The requested URL was not found on the server.",
  "instance": "/api/v1/missing",
  "code": "NOT_FOUND",
  "request_id": "00000000-0000-0000-0000-000000000000"
}
```

## Configuration

Copy `.env.example` to `.env`. Never commit `.env` or real credentials.

| Variable | Purpose | Development value |
| --- | --- | --- |
| `APP_ENV` | Active application environment | `development` |
| `SECRET_KEY` | Flask signing secret | Local placeholder only |
| `LOG_LEVEL` | Application log verbosity | `INFO` |
| `UPLOAD_ROOT` | Local upload directory | `storage/uploads` |
| `SMS_PROVIDER` | SMS adapter selection | `fake` |
| `PAYMENT_PROVIDER` | Payment adapter selection | `fake` |
| `SERVICE_NAME` | Service identifier in health responses | `neurotech-api` |
| `SERVICE_VERSION` | API service version | `0.1.0` |
| `PROBLEM_BASE_URI` | Base URI for RFC 9457 problem types | Local API URI |
| `DATABASE_URL` | Limited MariaDB development connection | `neurotech_dev` database |
| `TEST_DATABASE_URL` | Isolated integration-test connection | `neurotech_test` database |
| `REDIS_URL` | Redis connection pool target | WSL2 localhost |
| `REDIS_NAMESPACE` | Environment key prefix | `neurotech:dev` |
| `JWT_SECRET_KEY` | JWT signing key | Local placeholder only |

Production secrets must be supplied through the deployment environment rather
than committed files.

## Tests and code quality

`requirements.txt` contains the build, runtime, testing, and linting packages
needed by the current implementation. Keep it synchronized with
`pyproject.toml` whenever dependencies change.

After installing dependencies:

```powershell
pytest --cov-report=json:.coverage-report.json
ruff check .
ruff format --check .
python scripts/check_layer_coverage.py
```

Pytest uses the project-local `.pytest-tmp` directory instead of the Windows
global temporary directory. This avoids machine-specific permission problems;
the directory is generated automatically and ignored by Git.

If PowerShell reports that `.\.venv\Scripts\Activate.ps1` does not exist, create
the virtual environment before activating it:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

After activation, the PowerShell prompt should begin with `(.venv)`.

Test categories:

- `tests/unit`: domain and service tests without external infrastructure
- `tests/integration`: MariaDB and adapter integration tests
- `tests/api`: HTTP contract tests through the Flask test client

The suite covers domain rules, service branches, API contracts, OTP and rate
limits, authentication sessions, Academy, progress, moderation, orders, payment
idempotency, health responses, migrations, and RFC 9457 errors. In CI the same
suite runs against a real MariaDB and Redis service. Overall coverage must remain
at least 85%; branch coverage in `domain/services` must remain at least 95%.

## Confirmed decisions

- Architecture: Semi-Clean modular monolith
- Framework: Flask
- Database: MariaDB through SQLAlchemy ORM
- Migrations: Alembic
- Authentication: JWT in secure HttpOnly cookies
- Access token lifetime: 15 minutes
- Refresh token lifetime: 7 days with rotation
- Maximum authentication session: 30 days
- SMS: fake adapter initially, replaceable with the acquired provider
- Payment: fake adapter until the real gateway is available
- File storage: local persistent storage for lightweight assets
- Video: YouTube references rather than locally stored video files
- Dynamic content languages: Persian and English
- API identifiers, fields, codes, and routes: English
- Product sale mode: either `direct` or `inquiry`, never both
- Errors: RFC 9457 Problem Details

## Local files

Uploaded files will live under `storage/uploads` and are intentionally ignored
by Git. Only the empty directory marker is committed. The database will store
file metadata and relative paths, not binary file contents.

Fonts that ship with the frontend remain in the frontend repository unless
administrators need to manage them dynamically.

## MVP status

Roadmap phases 0–5 are implemented: the data foundation, JWT/OTP authentication,
Academy catalogue, enrollment/progress/moderation, and the fake checkout flow.
See the development guide for WSL2 provisioning and local verification. Later
product, event, CMS, and production deployment phases intentionally remain out
of the MVP.

## Contributing

- Keep changes scoped to one roadmap step.
- Add or update tests with every behavior change.
- Add migrations for every schema change.
- Do not place business rules in routes or ORM models.
- Do not commit `.env`, credentials, generated uploads, or local databases.
- Update this README whenever setup, configuration, or architecture changes.
