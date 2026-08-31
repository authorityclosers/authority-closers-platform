# Application secret contract

Application deployments read Infisical path `/application` from the `staging`
or `prod` environment. The VPS machine identity injects values only into the
short-lived `docker compose` process; no rendered environment file is written
to disk.

## Required per environment

| Secret                        | Constraint                                                                  |
| ----------------------------- | --------------------------------------------------------------------------- |
| `AC_POSTGRES_OWNER_PASSWORD`  | independent random database bootstrap credential                            |
| `AC_DB_MIGRATOR_PASSWORD`     | independent random migration-role credential                                |
| `AC_DB_RUNTIME_PASSWORD`      | independent random runtime-role credential                                  |
| `AC_DB_BACKUP_PASSWORD`       | independent random read-only backup credential                              |
| `AC_DATABASE_URL`             | `postgresql+psycopg://ac_runtime:<runtime-password>@postgres/ac_platform`   |
| `AC_DATABASE_MIGRATOR_URL`    | `postgresql+psycopg://ac_migrator:<migrator-password>@postgres/ac_platform` |
| `AC_SESSION_TOKEN_PEPPER`     | independent random value of at least 32 bytes                               |
| `AC_OAUTH_TRANSACTION_SECRET` | independent random value of at least 32 bytes                               |
| `AC_EMAIL_CHALLENGE_SECRET`   | independent random value of at least 32 bytes                               |
| `AC_GOOGLE_OAUTH_CLIENT_ID`   | Google web client ID ending in `.apps.googleusercontent.com`                |
| `AC_GOOGLE_OAUTH_CLIENT_SECRET` | non-empty secret for that exact Google web client                         |
| `AC_PUBLIC_LEARNER_TENANT_ID`   | exact active tenant UUID selected for public/self-directed learner access |
| `AC_OPERATIONS_TENANT_ID`       | exact existing control-tenant UUID required before side effects release   |

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

## Held integrations

`AC_RESEND_API_KEY` and the non-secret reviewed `AC_RESEND_FROM` may be present,
but the checked-in environment profile keeps `AC_EMAIL_PROVIDER=fake` and
external effects held until a separate provider activation gate. Enabling
Resend requires both names; the legacy unprefixed `RESEND_API_KEY` is not read.
Compose injects the selector, key, and sender into the worker only. The API and
migrator do not receive these variables or the mail credential; their provider
configuration remains at the application default `fake`. This process-level
least-privilege boundary applies even though Infisical supplies the values to
the short-lived Compose invocation.
The activation record must prove the sender domain, consent version, bounded
invitation volume, delivery/complaint monitoring, and a live verification plus
recovery journey without printing the key or recipient address.

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
