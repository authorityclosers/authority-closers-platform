# Sales Xray S1 processing hold diagnostics

## Change

The processing-plan scheduler still holds the plan with the existing public
`processing_authorization_or_input_unavailable` code after a caught local
authorization/input error. It now also persists one internal `diagnostic_code`
in the plan's existing progress JSON when that error is raised at `_enqueue`'s
approval evaluation, quote/usage/reservation call, or `request_stage` call. The
diagnostic is a fixed phase/category pair derived only from known local
exception classes. Diagnostic derivation does not inspect exception messages or
representations and does not persist provider data or source content. The public
plan view and acquisition progress do not project this diagnostic; the held
plan keeps the existing generic failure code.

This distinguishes the boundary and broad error category for later investigation;
it does not identify an incident root cause or authorize resuming a held plan.

## Evidence and constraints

- `processing_plan.py` wraps only the three named `_enqueue` calls. Exceptions
  retain their original type and flow into the existing scheduler handler. The
  scheduler's nested transaction still rolls back partial work before persisting
  the held plan.
- `authority.py` performs current approval, quote validation, account checks,
  and reservation checks. `inference.py` performs final admission and quote
  validation before recording budget snapshots, an outbox job, run, task, and
  receipt. The scheduler does not invoke a provider worker.
- `ConversationProcessingPlans.view` does not include the internal diagnostic;
  `acquisition_reports.py` still projects the allowlisted generic failure code.
- `docs/implementation/sales-xray-execution-control-20260914.md` preserves the
  durable dispatch fence and says an already-started provider effect may
  complete. This change does not alter that fence or any retry behavior.
- The production hold's original exception was not retained. No cause is
  attributed here, and no attempt is made to move the held analysis forward.

## Verification

- Unit tests for processing plans and acquisition progress: **46 passed**.
- The PostgreSQL processing-plan module, including three injected failures
  across approval, quote/reservation, and `request_stage`, collected **20 tests**.
  Those rollback tests were not executed in this environment because no explicit
  disposable loopback PostgreSQL URL was configured.
- Ruff check, Ruff format check, and `git diff --check`: passed.
- No provider calls, production access, SQL edits, or UI changes were made.
