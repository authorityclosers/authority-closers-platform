# RISK11/12/15 recovery safety evidence

Date: 2026-09-22

Base: `1a16a4b8defe0f4c36cc4bda5b72ada02c005b17`

Candidate: `codex/sales-xray-reliable-20260922`

Scope: acquisition progress diagnostics, generic Admin outbox retry fencing,
and terminal inference task reuse.

This receipt covers synthetic local verification only. It records no live
provider call, production database mutation, operational SQL repair, secret,
customer audio, or provider response body.

## PostgreSQL proof

A disposable PostgreSQL 18 container and a Python 3.12 Bookworm test
container shared the PostgreSQL network namespace. The test container used the
repository as a writable mount because the existing fixture builds and invokes
the reviewed native AudioAtlas executable. The native build was performed
explicitly after container startup:

```text
docker run -d --rm --name ac-xray-safety-pg \
  -e POSTGRES_HOST_AUTH_METHOD=trust postgres:18

docker run -d --rm --name ac-xray-safety-py \
  --network container:ac-xray-safety-pg \
  -v C:\Users\Suyash\.codex\worktrees\sales-xray-reliable-20260922\authority-closers-platform:/workspace \
  -w /workspace python:3.12-bookworm sleep infinity

docker exec ac-xray-safety-py apt-get update
docker exec ac-xray-safety-py apt-get install -y --no-install-recommends cmake g++ ffmpeg
docker exec ac-xray-safety-py python -m pip install --disable-pip-version-check --no-cache-dir -e . pytest pytest-asyncio ruff
docker exec ac-xray-safety-py python -c "from ac_platform.conversation_intelligence.signals import build_native; print(build_native())"
```

The shared-network loopback connection was checked with
`postgresql://postgres@127.0.0.1:5432/postgres`. Each PostgreSQL fixture then
created an isolated schema. The environment used by the test commands was:

```text
PYTHONPATH=packages/python
AC_CONVERSATION_POSTGRES_TEST_URL=postgresql+psycopg://postgres@127.0.0.1:5432/postgres
AC_TEST_DATABASE_URL=postgresql+psycopg://postgres@127.0.0.1:5432/postgres
```

The RISK15 pre-dispatch regression and the Admin generic-retry journey passed:

```text
docker exec -e PYTHONPATH=packages/python \
  -e AC_CONVERSATION_POSTGRES_TEST_URL=postgresql+psycopg://postgres@127.0.0.1:5432/postgres \
  -e AC_TEST_DATABASE_URL=postgresql+psycopg://postgres@127.0.0.1:5432/postgres \
  ac-xray-safety-py python -m pytest -q \
  --basetemp /tmp/ac-xray-reliable-safety-2 \
  tests/database/test_conversation_inference_postgresql.py::test_fresh_provider_request_does_not_reuse_terminal_pre_dispatch_task \
  tests/integration/test_operations_http_postgresql.py::test_operations_http_postgresql_authorization_replay_and_webhook_journey

2 passed in 30.36s
```

The acquisition progress HTTP regressions passed, including the deadlock
retry parameterization (three executed cases):

```text
docker exec -e PYTHONPATH=packages/python \
  -e AC_CONVERSATION_POSTGRES_TEST_URL=postgresql+psycopg://postgres@127.0.0.1:5432/postgres \
  -e AC_TEST_DATABASE_URL=postgresql+psycopg://postgres@127.0.0.1:5432/postgres \
  ac-xray-safety-py python -m pytest -q \
  --basetemp /tmp/ac-xray-reliable-safety-progress \
  tests/database/test_conversation_submission_http_postgresql.py::test_progress_retries_one_deadlock_in_a_fresh_owner_transaction \
  tests/database/test_conversation_submission_http_postgresql.py::test_progress_deadlock_retry_is_bounded_and_code_specific

3 passed in 48.50s
```

The focused local unit set covering the changed inference, processing-plan,
acquisition-report, outbox, and operations paths passed **123 tests**. Ruff
lint/format checks and `git diff --check` passed for all owned implementation
and test files. The disposable containers were removed after the receipts were
collected.

The first container attempt before the explicit native build failed in the
pre-existing local C1 fixture with `conversation_local_phase_failed`; that
attempt is not counted as a proof. Rebuilding AudioAtlas for the Linux test
container produced the platform-correct binary and manifest, after which the
commands above passed.

## Independent wrapper/workflow review

An independent read-only review covered
`scripts/ci/verify_sales_xray_acquisition_browser.py` and the dedicated
`validate-sales-xray-acquisition-browser` job in
`.github/workflows/application.yml`. The review found no P1 or P2 defect.

The reviewed contract invokes exactly
`tests/e2e/test_sales_xray_acquisition_browser.py::test_compiled_guest_upload_report_reload_claim_and_deletion`,
requires one non-skipped JUnit case, verifies the production build identity,
requires the isolated PostgreSQL URLs and verified native prerequisite,
rejects API/provider interception, page errors, missing or stale bounded
receipts, and uploads the sanitized receipt/proof artifacts. The local browser
proof is recorded separately in `browser-local-proof.json`,
`browser-local-receipt.json`, and
`docs/evidence/sales-xray-acquisition-browser-ci-gate-20260922.md`.

No deployment, provider activation, production mutation, or commit was made
by this evidence task.
