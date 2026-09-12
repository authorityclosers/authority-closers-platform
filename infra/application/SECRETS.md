# Application secret contract

Application deployments read Infisical path `/application` from the `staging`
or `prod` environment. The VPS machine identity injects values only into the
short-lived `docker compose` process; no rendered environment file is written
to disk.

## Required per environment

| Secret                          | Constraint                                                                  |
| ------------------------------- | --------------------------------------------------------------------------- |
| `AC_POSTGRES_OWNER_PASSWORD`    | independent random database bootstrap credential                            |
| `AC_DB_MIGRATOR_PASSWORD`       | independent random migration-role credential                                |
| `AC_DB_RUNTIME_PASSWORD`        | independent random runtime-role credential                                  |
| `AC_DB_BACKUP_PASSWORD`         | independent random read-only backup credential                              |
| `AC_DATABASE_URL`               | `postgresql+psycopg://ac_runtime:<runtime-password>@postgres/ac_platform`   |
| `AC_DATABASE_MIGRATOR_URL`      | `postgresql+psycopg://ac_migrator:<migrator-password>@postgres/ac_platform` |
| `AC_SESSION_TOKEN_PEPPER`       | independent random value of at least 32 bytes                               |
| `AC_OAUTH_TRANSACTION_SECRET`   | independent random value of at least 32 bytes                               |
| `AC_EMAIL_CHALLENGE_SECRET`     | independent random value of at least 32 bytes                               |
| `AC_GOOGLE_OAUTH_CLIENT_ID`     | Google web client ID ending in `.apps.googleusercontent.com`                |
| `AC_GOOGLE_OAUTH_CLIENT_SECRET` | non-empty secret for that exact Google web client                           |
| `AC_PUBLIC_LEARNER_TENANT_ID`   | exact active tenant UUID selected for public/self-directed learner access   |
| `AC_OPERATIONS_TENANT_ID`       | exact existing control-tenant UUID required before side effects release     |

The four database passwords must be distinct. The three identity secrets must
also be mutually distinct. The two SQLAlchemy URLs must be
constructed from the matching role passwords and must never use the owner or
backup role.

Google OAuth is mandatory for every activated staging and production release.
The installer clears ambient OAuth credentials, loads the Infisical values,
and rejects a missing, empty, whitespace-only, or partial pair before image
loading or any Compose command. This preflight reports variable names only,
never values. Compose, settings validation, and application composition retain
independent required-pair checks. The Google web client must contain the exact
same-surface callback URLs listed in the application release contract.
This preflight proves configuration presence only; credential rotation and a
real Google login/callback remain deployment-time operational evidence.

## Provider activation profiles

The reviewed staging and production profiles select `AC_EMAIL_PROVIDER=resend`
and `AC_EXTERNAL_SIDE_EFFECTS_HOLD=false`. Production activation is a separate
immutable release after the held bootstrap release; it requires verified active
operations/public-learner tenant references and independently reviewed prod
`/application` provider facts. The production `AC_RESEND_API_KEY` and reviewed
`AC_RESEND_FROM` must be present as one pair, with the sender domain verified.
No sender or key is embedded in source. Enabling Resend requires both provider
names; the legacy unprefixed `RESEND_API_KEY` is not read.
Compose injects the selector, key, and sender into the worker only. The API and
migrator do not receive these variables or the mail credential; their provider
configuration remains at the application default `fake`. This process-level
least-privilege boundary applies even though Infisical supplies the values to
the short-lived Compose invocation.
The activation record must prove the sender domain, consent version, bounded
invitation volume, delivery/complaint monitoring, and a live verification plus
recovery journey without printing the key or recipient address.

Changing the source profile does not reconcile the durable recovery generation
or authorize a backlog of sends. The worker also requires persisted recovery
state `READY`; held work must use the existing audited recovery path. Verify the
production queue and approved initial delivery scope before releasing the worker.

`AC_LEARNER_CONSENT_VERSION` is release-owned configuration: the installer clears
ambient and injected values before applying the release profiles. Production
registration therefore requires the exact approved consent version in its
reviewed profile contract; adding it only to Infisical is insufficient. This
email activation retains `ac-learner-terms-privacy-2026-09-13-v1` from the separately
reviewed consent-profile release.

`AC_PUBLIC_LEARNER_TENANT_ID` is not authority by itself. It points to the
canonical active tenant whose persisted membership rows remain the authorization
source of truth. Keep it in the environment-scoped secret/config store so a
staging identifier cannot be reused accidentally in production.

`AC_OPERATIONS_TENANT_ID` is also a reference, not authority. A first, empty
environment may omit it only while `AC_EXTERNAL_SIDE_EFFECTS_HOLD=true`. That
held bootstrap phase keeps the worker unavailable and makes every tenantless
retry/recovery operation fail closed. Before the hold is released, select an
exact existing active control tenant in Infisical; deployment validation then
requires it. The selected actor must be an owner of that exact tenant and hold
the separate global retry/recovery permissions. Actions and idempotency markers
remain attributable in the control tenant's append-only audit chain.

Release SHA, image IDs, registry digests, URLs, Compose project names, state
paths, and edge aliases are non-secret reviewed release metadata. They belong
in the Git archive or workflow artifact, not Infisical.

Do not copy production database or identity secrets into staging. Rotation is
create-new, update Infisical, prove a candidate deployment, then revoke-old;
never overwrite a working recovery path before the replacement is verified.
