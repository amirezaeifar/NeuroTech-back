# NeuroTech Backend

Backend API for the NeuroTech platform, built with Python and Flask using a
Semi-Clean modular monolith architecture.

The current MVP includes MariaDB migrations, Redis-backed OTP and rate limiting,
JWT cookie authentication, role checks, Academy and product catalogues,
enrollments, lesson progress, moderated comments, product inquiries, direct
orders, local asset uploads, events/reservations, and idempotent development
payment gateways. It also includes bilingual partner profiles, global-trade
documents, and publishable page-content overrides for the dynamic sections of
the website. HTTP errors use RFC 9457 Problem Details.

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

The upload API accepts small images, PDFs, text files, and web fonts up to 8 MB.
It rejects executable and video extensions. Files are stored under a random
key, while their original name, MIME type, size, SHA-256 digest, visibility,
and relative key are held in MariaDB.

## YouTube course playlists

Course video bytes never pass through this backend. Set
`youtube_playlist_id` on a course from the Admin course API. The frontend loads
that playlist through the YouTube iframe player and treats each lesson's
position as the corresponding playlist position. Lesson records remain in the
database for titles, access rules, and progress tracking; their legacy
`video_reference` is a fallback when a playlist has not yet been assigned.

Store only the playlist ID (for example, the value after `list=`), not the full
YouTube URL. The channel or playlist must permit embedding.

## Product sale modes

Every product has exactly one `sale_mode`:

- `direct`: requires stock and at least one IRR/USD price; it can enter the cart
  and continue to a product order and payment.
- `inquiry`: has no checkout price and accepts customer quotation requests with
  the `pending`, `answered`, `closed`, or `rejected` workflow.

## Implementation status

Roadmap phases 0–9 are implemented: the data foundation, JWT/OTP authentication,
Academy, enrollment/progress/moderation, course checkout, products, direct
product sales and inquiries, safe local asset uploads, YouTube course playlists,
and events with capacity-aware reservations and speaker-to-user-profile links.
The admin manages products, events, partner resumes and guest support tickets.
Global Trade and general page copy are static in the frontend; legacy trade and
page-content API records remain preserved but are no longer used by the site.
The Partners page introduction stays static while profile cards and resumes read
from the same partner API. Contact page copy stays static; its form persists tickets.
Real SMS and payment provider adapters and production deployment remain later work.

## Admin content API

Admin and specialist roles can manage the dynamic website sections through:

- `/api/v1/admin/products` and `/api/v1/admin/product-categories`
- `/api/v1/admin/events`
- `/api/v1/admin/partners`
- `/api/v1/admin/trade-documents`
- `/api/v1/admin/page-content`

Partner profiles and global-trade documents have public read endpoints under
`/api/v1/partners` and `/api/v1/trade-documents`. Draft or archived records are
never returned by public endpoints. The page-content API only accepts the five
managed page keys listed above and rejects `home`, `about`, and `contact`.

## Contributing

- Keep changes scoped to one roadmap step.
- Add or update tests with every behavior change.
- Add migrations for every schema change.
- Do not place business rules in routes or ORM models.
- Do not commit `.env`, credentials, generated uploads, or local databases.
- Update this README whenever setup, configuration, or architecture changes.

## Admin refresh and guest support (2026-09-10)

Apply `python -m alembic upgrade head` (revision `20260910_0009`), then run
`python -m flask --app app:create_app seed-partners`. The latter imports the four
original bilingual frontend resumes from `app/data/partners.json`, skipping any
existing slug so later administrator edits are preserved.

Course translations now include an optional `summary`; public course payloads
include `images` for `cover_light`, `cover_dark`, `header_light`, `header_dark`.
Product translations have a `details` object for per-product specifications,
features, certifications, clinical evidence, software details and brochure links.
Empty arrays remain empty on public pages instead of falling back to demo claims.

Guest support endpoints:

- `POST /api/v1/tickets`: name, valid phone, subject, message, optional email and
  `locale` (`fa` or `en`). No account required; rate limited to 5/minute.
- `GET /api/v1/tickets/track/{token}`: unguessable tracking token returned on
  submission; public response excludes contact details and internal SMS metadata.
- `GET /api/v1/admin/tickets`: admin-only, `q`, `status`, `page`, `page_size`.
- `GET /api/v1/admin/tickets/{id}`: admin contact details and conversation history.
- `PATCH /api/v1/admin/tickets/{id}`: `status`, `reply`, and the current `version`.
  Statuses: `submitted`, `in_progress`, `resolved`. Stale writes return 409;
  resolving a request requires a response. Responses are visible via guest tracking.

Ticket history and SMS notification results persist in MariaDB. `SMS_PROVIDER=fake`
records simulated notifications for receipt, progress and completion; no SMS is
actually delivered. Keep the tracking link shown after submission. Notifications
use `FRONTEND_URL`; adapter failures leave the ticket saved and record `failed` in
its history. The existing SMS interface remains the replacement point for a real
provider. Administrators currently respond in the website; mock SMS is a notice,
not a live messaging integration.

Browser verification: `tests/browser_fixture.py <temporary-cookie-file>` starts a
seeded temporary SQLite backend on 5001, then removes its temporary data on exit.
Use the frontend's `tests/admin.browser.cjs` with Vite on 5174 and
`VITE_API_BASE_URL=http://127.0.0.1:5001/api/v1`. This never uses the development DB.
# Real email, SMS, and country counts

For real delivery, set `EMAIL_PROVIDER=smtp` and `SMS_PROVIDER=kavenegar` in your private
`.env`. Gmail uses `SMTP_HOST=smtp.gmail.com`, `SMTP_PORT=587`,
`SMTP_USERNAME=neuro.tech.pishro@gmail.com`, and `EMAIL_FROM` with the same address.
Set `SMTP_PASSWORD` to a Google **App Password** for that mailbox, never the account
password. Set `KAVENEGAR_API_KEY` from your Kavenegar account, `KAVENEGAR_SENDER=20006535`,
and `KAVENEGAR_LOGIN_TEMPLATE=surgitrack-login`. The login template must accept the
single `token` supplied by the app. Do not commit credentials.

Country counts use the free DB-IP Country Lite `.mmdb` file at `GEOIP_DATABASE_PATH`.
Run `python scripts/update_geoip.py` from this directory, then schedule it monthly
to keep the database current. No account is needed. DB-IP requires attribution on
the page showing country statistics. Set `TRUSTED_PROXY_IPS` to the
actual reverse proxy addresses so client IPs are read from their forwarded header.
Unknown and private IPs do not contribute to a country count.

Event reservations now require a verified account email. Requesting a seat emails
a confirmation link; the seat is assigned only when that link is opened within
24 hours. Capacity is checked again at confirmation, so a pending link does not
guarantee a seat.
