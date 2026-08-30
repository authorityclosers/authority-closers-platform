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

The four database passwords must be distinct. The two SQLAlchemy URLs must be
constructed from the matching role passwords and must never use the owner or
backup role.

## Optional, fail-closed integrations

`AC_GOOGLE_OAUTH_CLIENT_ID` and `AC_GOOGLE_OAUTH_CLIENT_SECRET` are an
all-or-nothing pair. Until the Google web client contains the exact staging or
production same-surface callback URLs, omit both and leave Google login
disabled. `RESEND_API_KEY` may be present, but the checked-in environment
profile keeps `AC_EMAIL_PROVIDER=fake` and external effects held until a
separate provider activation gate.

Release SHA, image IDs, registry digests, URLs, Compose project names, state
paths, and edge aliases are non-secret reviewed release metadata. They belong
in the Git archive or workflow artifact, not Infisical.

Do not copy production database or identity secrets into staging. Rotation is
create-new, update Infisical, prove a candidate deployment, then revoke-old;
never overwrite a working recovery path before the replacement is verified.
