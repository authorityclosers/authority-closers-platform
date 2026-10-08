# AUT-1551: lightweight container health checks

Lane: devenv. Tier: non-routine. Scope includes the dev Admin image adapter so
its ninth web container adopts the same probe as staging when its image refreshes.

HTTP checks use a POSIX shell with native curl; only Sales Xray also starts jq to
validate its JSON identity. No Node or Python interpreter starts for these probes.
The helper lives under `infra/sales-xray-web/` so changes remain covered by that
image workflow's existing input filter. Runtime Dockerfiles install the tools
and copy the helper with mode 0555. Images and compose must ship together through
the existing release path.

| Service              | Endpoint                           | Preserved condition                                                                                        | Interval / start period       |
| -------------------- | ---------------------------------- | ---------------------------------------------------------------------------------------------------------- | ----------------------------- |
| API                  | `/health/ready`, port 8000         | GET with `AC_API_HOST` Host header; final HTTP 2xx                                                         | 30 s / 30 s                   |
| Learner              | `/`, port 3000                     | GET, follow sign-in redirects; final HTTP 2xx                                                              | 30 s / 30 s                   |
| Admin                | `/healthz`, port 3001              | GET on container loopback; final HTTP 2xx                                                                  | 30 s / 30 s                   |
| Coach                | `/healthz`, port 3002              | GET on container loopback; final HTTP 2xx                                                                  | 30 s / 30 s                   |
| Sales Xray           | `/health`, port 3016               | Final HTTP 2xx; one JSON response with `status=ok`, `service=sales-xray-web`, and matching `AC_RELEASE_ID` | 30 s / 30 s                   |
| Application Postgres | Existing psql bootstrap-role query | Authentication, target database and all three bootstrap roles                                              | 15 s / 20 s                   |
| Local Postgres       | Existing pg_isready check          | Same readiness condition                                                                                   | 15 s / existing configuration |

Timeouts, retry counts and container resource limits remain as configured. Curl
has a three-second request deadline. It ignores curlrc and proxy variables for
container loopback probes. Final non-2xx responses fail, including HTTP 304.

The dev Admin adapter reads the immutable image's
`com.authorityclosers.http-healthcheck=1` label and writes the new health check
into its existing source-managed override only for compatible images. Older
images keep their existing check. The existing rollback restores the previous
override and image; deployment tests cover both paths. No env file, host service,
database or deployed container was changed by this implementation run.

## Local verification

`uv run pytest tests/infra/test_http_healthcheck.py
tests/infra/test_deploy_dev_admin_web.py tests/infra/test_application_release.py
tests/unit/releases/test_sales_xray_web_artifact.py -q`: **141 passed, 1 skipped**.
The skipped test requires Docker for the existing Caddy selector mount proof;
the lane session has no usable Docker daemon. CI requires that proof to pass.

The new HTTP tests run the actual helper, curl and jq against a loopback fixture.
They cover successful/failed status codes, redirects, the API Host header,
readiness failure, malformed JSON, service/release mismatches, multiple JSON
documents, and connection refusal. Ruff formatting/lint, shell syntax and
`git diff --check` also pass.

## Deployment acceptance still required

BEFORE evidence from [AUT-1562](/AUT/issues/AUT-1562): **0.65 containerd CPU seconds
over 60.000358216 seconds**, or **1.083326866% of one logical CPU**.
[Sanitized inventory and measurement receipts](/api/attachments/e90aee91-7fd7-4b86-8ff7-02174c3add54/content?download=1)
have SHA-256 `bcc481f68c2c9eed2ad4a6510c79dcace12c803d3c265a4d11a431439132ce03`.
The recorded inventory had 15 healthy configured checks and eight containers
without a health check. This is containerd CPU, not total probe CPU.

AFTER CPU, deployed dev/staging health and the staging release canary are pending.
Root Operator owns host execution after the reviewed change merges and the
release train stores the matching images. Measure the same process ticks over
60 seconds, record the actual container/image/probe inventory and any unchanged
production probes, and attach the result to the PR. Do not infer a saving from
the changed intervals or fabricate an AFTER measurement from a local benchmark.
