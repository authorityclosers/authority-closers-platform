# Sales Xray launch-repair evidence

**Date:** 2026-09-17
**Base:** `codex/guest-retained-c2-recovery-20260916` at `3ef1a372`

## Scope

The supplied `sales-xray-launch-audit.zip` was treated as untrusted evidence. Its
candidate patch was not applied because the checked-out branch is newer and its
Sales Xray transport/UI sources differ from the audited SHA.

This change addresses the current source-level recovery risks:

- acquisition requests now bound headers and JSON-body consumption with a child
  abort signal; timeout copy does not claim that an uncertain mutation failed;
- selected audio moments consume their end boundary after pausing;
- report-level “Analyse another call” preserves the opaque saved-call selector;
- poll transport errors are separate from action errors and clear after a
  successful status read;
- ASGI receive frames are split into storage-sized writes after cumulative-size
  validation; and
- progress reads the newest bounded task window with deterministic tie ordering,
  then presents it chronologically to the existing client contract.

## Verification

- `pnpm --filter @ac/sales-xray-web test` focused recovery set: 66 passed.
- `uv run pytest tests/unit/conversation_intelligence/test_intake_transport.py tests/unit/conversation_intelligence/test_acquisition_reports.py -q`: 10 passed.
- Sales Xray TypeScript typecheck: passed.
- Workspace TypeScript typecheck: passed.
- Full Python Ruff and mypy checks: passed.
- Sales Xray production build: passed.

## Remaining release blockers

The host has Node `22.17.0`; repository CI requires Node `24.19.0`. Full service-backed
PostgreSQL, browser, provider, deployment-identity, accessibility and production
journey gates remain unverified. A parallel Windows Vitest run also hit a temporary
cache-file rename error after 191 assertions passed; the affected
`report-explorer.test.tsx` passes when rerun serially with one worker.
