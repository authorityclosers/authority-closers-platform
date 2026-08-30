# Environment contract

Production configuration is injected from Infisical at process start. Git contains names and safe local defaults only.

| Variable                         | Owner             | Required outside local | Purpose                                                 |
| -------------------------------- | ----------------- | ---------------------: | ------------------------------------------------------- |
| `AC_ENVIRONMENT`                 | release           |                    yes | `development`, `staging`, or `production` behavior gate |
| `AC_RELEASE_ID`                  | release           |                    yes | immutable Git-derived release identity                  |
| `AC_DATABASE_URL`                | runtime identity  |                    yes | least-privilege application connection                  |
| `AC_DATABASE_MIGRATOR_URL`       | deploy identity   |            deploy only | schema migration connection                             |
| `AC_GOOGLE_OAUTH_CLIENT_ID`      | identity provider |                    yes | Google web OAuth client identifier                      |
| `AC_GOOGLE_OAUTH_CLIENT_SECRET`  | identity provider |                    yes | Google web OAuth client secret                          |
| `AC_EXTERNAL_SIDE_EFFECTS_HOLD`  | recovery operator |                    yes | blocks provider effects after restore                   |
| `AC_EMAIL_PROVIDER`              | provider policy   |                    yes | `fake` until Resend is explicitly enabled               |
| `AC_OTEL_EXPORTER_OTLP_ENDPOINT` | telemetry         |                    yes | trace/metric collector endpoint                         |
| `AC_PUBLIC_APP_URL`              | edge              |                    yes | learner origin and redirect allowlist source            |
| `AC_ADMIN_APP_URL`               | edge              |                    yes | admin origin and redirect allowlist source              |
| `AC_API_URL`                     | edge              |                    yes | canonical API origin                                    |
| `AC_API_HOST`                    | edge              |                    yes | canonical public API host and health probe Host         |
| `AC_INTERNAL_API_HOST`           | release           |                    yes | reserved app-network-only API DNS name                  |

Canonical staging origins are `https://staging.authorityclosers.com`,
`https://admin-staging.authorityclosers.com`, and
`https://api-staging.authorityclosers.com`. Canonical production origins are
the `app`, `admin`, and `api` first-level subdomains. Deep staging subdomains are
not used because the free Cloudflare Universal SSL certificate does not cover a
second subdomain label.

The non-secret release profile additionally fixes `AC_COMPOSE_PROJECT`,
`AC_STATE_ROOT`, `AC_API_HOST`, `AC_INTERNAL_API_HOST`, and three
environment-specific edge aliases.
The workflow-produced `release-images.env` binds the full Git SHA to exact image
IDs and private-registry provenance digests. Staging and production promotion
must reuse that identical file.

Compose assigns only the environment's reserved `AC_INTERNAL_API_HOST` to the
API container on the isolated application network:
`api.staging.ac.internal.invalid` or
`api.production.ac.internal.invalid`. The admin server's internal URL is
exactly `http://<AC_INTERNAL_API_HOST>:8000`; its adapter rejects any host/URL
mismatch or alternate origin before making a request and does not override
Node's transport-owned `Host` header. Loss of the alias produces a `.invalid`
DNS failure rather than a plaintext request to public DNS. `AC_API_HOST`
remains the canonical public API host used by the edge and API health probe.

Activated staging and production also fix the cookie names to
`__Host-ac_session` and `__Host-ac_oauth_transaction`. The API emits them only
with `Secure`, `HttpOnly`, `SameSite=Lax`, `Path=/`, and no `Domain`, and rejects
missing, malformed, or duplicate raw security-cookie fields before identity or
OAuth callback resolution.

Secrets such as database passwords, OAuth credentials, signing keys, provider tokens, and R2 credentials are intentionally absent. No client-exposed variable may contain a secret.

The Google OAuth client ID and secret are mandatory for activated staging and
production. Test and development may omit the pair, but supplying either value
requires both values and whitespace-only values are treated as empty.
