# Local v0.1 alpha runbook

This runbook starts the implementation candidate. It does not activate a real
email provider, approve content beyond the controlled v0.1 Module 1 slice, or
make local state authoritative.

## Prerequisites

- Node 24.x and pnpm 11.x
- Python 3.12 or 3.13, plus `uv`
- a healthy Docker daemon for PostgreSQL, Mailpit, and telemetry dependencies

```powershell
pnpm install --frozen-lockfile
uv sync --frozen
Copy-Item .env.example .env
pnpm run dev:dependencies
uv run alembic upgrade head
uv run python -m ac_platform.seed.cli --help
pnpm dev
```

Use the reviewed staging seed command in
[`STAGING_FREE_COURSE_SEED.md`](STAGING_FREE_COURSE_SEED.md); do not invent or
edit course rows directly. Local endpoints are learner `http://localhost:3000`,
admin `http://localhost:3001`, and API `http://localhost:8000`.

## Required secret references

Local `.env` uses conspicuous non-production placeholders. Staging/production
must inject independent values from the approved secret manager for:

- `AC_SESSION_TOKEN_PEPPER`
- `AC_OAUTH_TRANSACTION_SECRET`
- `AC_EMAIL_CHALLENGE_SECRET`
- database role credentials and URLs
- Google OAuth pair
- `AC_PUBLIC_LEARNER_TENANT_ID` for the exact active self-directed learner tenant
- `AC_OPERATIONS_TENANT_ID` for an existing operations-control tenant before
  external side effects are released
- `AC_RESEND_API_KEY` when and only when the reviewed profile enables Resend

Never copy secret values into Git, commands, logs, screenshots, evidence, or
this runbook. The release Compose contract rejects missing identity/database
values; application settings reject default, short, or reused identity
secrets. An empty environment may leave `AC_OPERATIONS_TENANT_ID` blank only
while `AC_EXTERNAL_SIDE_EFFECTS_HOLD=true`; settings reject releasing the hold
without the exact existing control tenant.

Keep the local database host as `127.0.0.1`. The Compose port is deliberately
published on IPv4 loopback only; using `localhost` can make Windows async
clients wait for an IPv6 connection timeout before falling back to IPv4.

The checked-in defaults leave both tenant IDs blank and therefore fail closed:
public learner registration/login provisioning and tenantless authentication-
email retry or recovery are unavailable until an authorized bootstrap has
created or selected the existing tenant records and the secret manager injects
their exact IDs. Do not invent a tenant ID or create one with direct SQL.

## Validation

```powershell
pnpm run validate
uv run alembic heads
git diff --check
```

With PostgreSQL available, export the repository's documented test URLs and
rerun `uv run pytest`. A green run with PostgreSQL integration tests skipped is
not database runtime evidence.

## Runtime smoke

```powershell
curl.exe --fail http://localhost:8000/health/live
curl.exe --fail http://localhost:8000/health/ready
curl.exe --fail http://localhost:3000/manifest.webmanifest
curl.exe --fail http://localhost:3000/offline
```

Verify registration, verification, login, onboarding resume, recovery, reset,
session revocation, enrollment, draft/evidence, progress, and tenant-negative
paths through browser/API tests. Do not recover users with direct SQL.

## Known local stop conditions

- `AC_EMAIL_PROVIDER=fake` records acceptance but sends no user email. Real
  registration/recovery is therefore not operational evidence.
- If Docker/PostgreSQL is unhealthy, migrations, tenancy isolation, recovery,
  concurrency, and the fresh password journey remain unproven.
- The staging consent identifier is a test document marker, not production
  legal approval.
- The controlled seed and learner provisioning path are implemented, but they
  become runtime evidence only after PostgreSQL tests, exact-tenant
  configuration, seed application, and browser/API smoke pass.
- Modules 2–4 are topology-only extension contracts. Only Module 1 carries the
  v0.1 learning loop.
