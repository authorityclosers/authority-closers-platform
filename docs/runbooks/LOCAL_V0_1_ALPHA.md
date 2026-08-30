# Local v0.1 alpha runbook

This runbook starts the implementation candidate. It does not activate a real
email provider, approve course content, or make local state authoritative.

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

Never copy secret values into Git, commands, logs, screenshots, evidence, or
this runbook. The release Compose contract rejects missing values; application
settings reject default, short, or reused identity secrets.

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
- Course seed and automatic learner tenant membership remain controlled-source
  decisions; do not infer either.
