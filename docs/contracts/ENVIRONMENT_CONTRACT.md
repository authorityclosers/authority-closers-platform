# Environment contract

Production configuration is injected from Infisical at process start. Git contains names and safe local defaults only.

| Variable                         | Owner             | Required outside local | Purpose                                                 |
| -------------------------------- | ----------------- | ---------------------: | ------------------------------------------------------- |
| `AC_ENVIRONMENT`                 | release           |                    yes | `development`, `staging`, or `production` behavior gate |
| `AC_RELEASE_ID`                  | release           |                    yes | immutable Git-derived release identity                  |
| `AC_DATABASE_URL`                | runtime identity  |                    yes | least-privilege application connection                  |
| `AC_DATABASE_MIGRATOR_URL`       | deploy identity   |            deploy only | schema migration connection                             |
| `AC_EXTERNAL_SIDE_EFFECTS_HOLD`  | recovery operator |                    yes | blocks provider effects after restore                   |
| `AC_EMAIL_PROVIDER`              | provider policy   |                    yes | `fake` until Resend is explicitly enabled               |
| `AC_OTEL_EXPORTER_OTLP_ENDPOINT` | telemetry         |                    yes | trace/metric collector endpoint                         |
| `AC_PUBLIC_APP_URL`              | edge              |                    yes | learner origin and redirect allowlist source            |
| `AC_ADMIN_APP_URL`               | edge              |                    yes | admin origin and redirect allowlist source              |
| `AC_API_URL`                     | edge              |                    yes | canonical API origin                                    |

Canonical staging origins are `https://staging.authorityclosers.com`,
`https://admin-staging.authorityclosers.com`, and
`https://api-staging.authorityclosers.com`. Canonical production origins are
the `app`, `admin`, and `api` first-level subdomains. Deep staging subdomains are
not used because the free Cloudflare Universal SSL certificate does not cover a
second subdomain label.

The non-secret release profile additionally fixes `AC_COMPOSE_PROJECT`,
`AC_STATE_ROOT`, `AC_API_HOST`, and three environment-specific edge aliases.
The workflow-produced `release-images.env` binds the full Git SHA to exact image
IDs and private-registry provenance digests. Staging and production promotion
must reuse that identical file.

Secrets such as database passwords, OAuth credentials, signing keys, provider tokens, and R2 credentials are intentionally absent. No client-exposed variable may contain a secret.
