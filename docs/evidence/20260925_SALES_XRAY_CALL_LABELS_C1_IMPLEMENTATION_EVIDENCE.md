# Sales Xray C1 call labels implementation evidence

Date: 2026-09-25  
Base revision: `2c2f8d0919c402eb4ef51e7f440083e07433ad87` (the shared worktree also contains uncommitted work).

## Behavior and controls

The backend now supports an owner-authored display name for a retained saved call. `PATCH /v1/conversation/acquisition/submissions/{submission_id}/label` requires the current account owner, a retained source, and a strong `If-Match` revision tag (`"call-label-N"`). The JSON body accepts `display_name` as text or `null` to clear it. Names are trimmed, preserve Unicode, and are limited to 120 code points; controls, surrogates, and blank strings are rejected. A same-value stale retry returns the current revision without a second audit event; a competing stale update conflicts.

Saved-call list, progress, and report responses expose `display_name` and `display_name_revision`. The display name is separate from immutable source filenames and report history. Each accepted change creates a revision row. Audit events contain resource, actor, request, and revision identifiers only; they do not contain name text. Label reads and writes pass through `GuestOwnership` owner and retention checks. Recording erasure and account-profile erasure purge label revisions in their existing deletion transactions.

## Verification

The real PostgreSQL proof used the repository's canonical portable launcher, bound only to `127.0.0.1:55600`, with the disposable `ac_local_sandbox` database and per-test random schemas. It did not use Docker, production data, or external provider calls.

- `tests/database/test_conversation_submission_labels_postgresql.py` plus `tests/database/test_conversation_submission_http_postgresql.py::test_progress_retries_one_deadlock_in_a_fresh_owner_transaction`: **6 passed**. This covered migration registration, HTTP and same-tenant isolation, competing updates and idempotent retry, recording erasure, account erasure, and the fresh-transaction deadlock retry.
- `tests/unit/identity/test_sales_xray_profile.py tests/unit/conversation_intelligence/test_submission_labels.py tests/database/test_model_registry.py`: **32 passed**.
- The wider existing submission HTTP and account-library regression run: **15 passed**. Its only failure was the progress deadlock test described below; the narrow transaction fix was then verified by the 6-test PostgreSQL run above.
- Ruff check and format, targeted mypy, and `git diff --check`: **passed**.
- `uv run alembic heads`: `20260925_0050 (head)`.

The first real PostgreSQL attempt used pytest's default temporary directory under a user directory that has a `.git` ancestor. The existing recording-storage guard correctly rejected that test storage root. The proof was rerun using a new, absent `C:\Windows\Temp` basetemp outside the repository ancestry; no storage guard was weakened.

The wider regression run then exposed a transaction-boundary issue: after the progress reader's deadlock retry rolled back the dependency-owned transaction, the route tried to hydrate the label on that old session and returned 422. Progress and label hydration now run together inside the original or fresh retry transaction. Label hydration uses the same `GuestOwnership.require_submission_owner` retention gate, avoiding a redundant report-reader call. The targeted deadlock regression and all C1 PostgreSQL cases pass together.

The private proof receipt records exact whole-file SHA-256 values, portable launcher input hashes, the sanitized test scope, and the observed failure/fix. It contains no database URL, password, customer content, or raw test logs.

## Independent review and verification follow-up — 2026-09-26

Baseline: `fb4b6f1fdbd82a237e935a5062d3b6652a3b9b66`, with the candidate files still uncommitted. Claude Opus reviewed the bounded C1 file set without editing files or using production access. Its static review was followed by local fixes and real database checks; the review alone is not acceptance evidence.

- Names containing only zero-width/format/combining characters are rejected. Explicit bidirectional override/isolate controls are rejected, while meaningful multilingual text, combining marks and joined emoji remain accepted.
- GET progress/report responses no longer emit an ETag that represents only the label revision. The JSON revision and PATCH response tag remain available for optimistic edits.
- The PostgreSQL concurrency proof now covers both identical retries and conflicting values. The retention proof now runs the actual retention scheduler and deletion worker and verifies that all label history is erased, storage is empty and the audit chain remains valid.
- The full C1, submission HTTP and account-library PostgreSQL suites passed together: **23 passed**, using a new disposable local schema and an absent temporary directory outside the repository. The earlier deadlock failure is no longer outstanding in that suite.
- Focused label normalization/revision tests: **32 passed**. Full Python type checking: **322 source files passed**. Ruff and whitespace checks passed for the changed code.

The suggestion to blank previous names on every rename was not adopted: accepted changes remain revisions, and the existing recording/account erasure boundary purges their private text. No other account-deletion ordering defect was demonstrated. A deterministic concurrent retention-versus-rename test remains useful before a wider UI release.

This evidence does not claim a deployed naming feature. The pending label migration depends on the also-uncommitted v6 selection migration; release integration must resolve that dependency without implicitly activating v6 or publishing unreviewed work. No provider requests or production mutations were made for this verification.
