# RISK15 coordinator and typed-reconciliation amendment

Date: 2026-09-22

Candidate: `codex/sales-xray-reliable-20260922`

This receipt covers the amended coordinator behavior and the PostgreSQL
regressions requested after the initial safety review. No product code was
edited by this review task.

## Independent review

The `ConversationProcessingPlans._enqueue` change was reviewed against the
public `ConversationInference.request_stage` fence. The coordinator now
observes an existing terminal task so `advance()` can publish the exact
content-free hold for a failed/uncertain C2 task or derive the separately
authorized bounded C5 repair. Returning that retained row does not dispatch a
provider call. Fresh public stage requests remain rejected by
`inference.request_stage` when the same cache key is terminal, so a new
accepted request cannot silently turn an old failed run into a new success.

The operations regression was reviewed for the same safety invariant. An
expired dispatch with provider-effect evidence remains dead-lettered; generic
Admin retry raises `ReconciliationRequiredError`, preserves dispatch and
idempotency markers, writes no generic retry audit, and does not become
claimable. The test no longer treats generic retry as typed reconciliation.

No P1 or P2 defect was found in these two amended diffs.

## Disposable Linux/PostgreSQL proof

The proof used a disposable PostgreSQL 18 container and a Python 3.12
Bookworm container sharing its network namespace. The repository was mounted
read/write only so the existing native fixture could build its reviewed
AudioAtlas executable. The test dependencies and native prerequisite were
prepared with:

```text
docker run -d --rm --name ac-xray-review-pg -e POSTGRES_HOST_AUTH_METHOD=trust postgres:18
docker run -d --rm --name ac-xray-review-py --network container:ac-xray-review-pg \
  -v C:\Users\Suyash\.codex\worktrees\sales-xray-reliable-20260922\authority-closers-platform:/workspace \
  -w /workspace python:3.12-bookworm sleep infinity
docker exec ac-xray-review-py apt-get update
docker exec ac-xray-review-py apt-get install -y --no-install-recommends cmake g++ ffmpeg
docker exec ac-xray-review-py python -m pip install --disable-pip-version-check --no-cache-dir -e . pytest pytest-asyncio ruff
docker exec ac-xray-review-py python -c "from ac_platform.conversation_intelligence.signals import build_native; print(build_native())"
```

The conversation regressions used loopback PostgreSQL URLs inside the shared
network namespace:

```text
docker exec -e PYTHONPATH=packages/python \
  -e AC_CONVERSATION_POSTGRES_TEST_URL=postgresql+psycopg://postgres@127.0.0.1:5432/postgres \
  -e AC_TEST_DATABASE_URL=postgresql+psycopg://postgres@127.0.0.1:5432/postgres \
  ac-xray-review-py python -m pytest -q --basetemp /tmp/ac-xray-review-conversation \
  tests/database/test_conversation_processing_plan_postgresql.py::test_processing_plan_repairs_returned_invalid_c5_once_and_publishes_repaired_report \
  tests/database/test_conversation_submission_http_postgresql.py::test_guest_duplicate_upload_reuses_uncertain_retained_c2_without_provider_call

2 passed in 43.65s
```

The operations database was migrated to Alembic head in the disposable
database with `AC_DATABASE_MIGRATOR_URL` and `AC_DATABASE_URL` both set to
`postgresql+psycopg://postgres@127.0.0.1:5432/postgres`. The exact renamed
regression then passed with `AC_OPERATIONS_POSTGRES_TEST_URL` set to the same
loopback URL:

```text
docker exec -e PYTHONPATH=packages/python \
  -e AC_OPERATIONS_POSTGRES_TEST_URL=postgresql+psycopg://postgres@127.0.0.1:5432/postgres \
  ac-xray-review-py python -m pytest -q --basetemp /tmp/ac-xray-review-operations \
  tests/database/test_operations_postgresql.py::test_expired_dispatch_requires_typed_reconciliation_before_postgresql_reclaim

1 passed in 4.28s
```

Ruff check/format and `git diff --check` passed for the reviewed coordinator
and operations regression files. Both disposable containers were removed
after the proof. No provider call, production database, deployment, secret,
or customer data was used.
