# Analysis-settings inspection for Sales Xray v0.2

The existing Admin service can now read bounded, newest-first immutable revision
history. `GET /v1/admin/conversation/analysis-settings/history` uses the same
verified operations-workspace authority as editing, a default page of ten, and
an exclusive `before_revision` cursor. It does not create commands or provider
jobs. Admin displays the saved limits with units and dates, preserves verified
pages on an error, rejects non-decreasing cursor responses, and aborts a stale
history request after a newly saved revision.

The existing `analysis_settings_cli` gains `--action show` and `--action history`
through this same service. Read actions reject mutation arguments. Existing
save invocations remain supported; production writes still require explicit
`--allow-production`. Reads continue to require a valid Admin identity,
operations tenant, environment and hosted release identity.

The form also rejects invalid whole-number limits locally before sending a save.
The server remains authoritative. No configuration limits, provider approvals,
stored revisions, accepted plans or budget controls are changed by this patch.

## Verification

On Windows, Python 3.12 and Node 24.19.0:

- `uv run pytest tests/unit/conversation_intelligence/test_analysis_settings.py
  tests/unit/conversation_intelligence/test_analysis_settings_cli.py
  tests/database/test_conversation_analysis_history_postgresql.py`: **16 passed**.
  PostgreSQL uses the existing disposable loopback runtime at port 55432; each
  test module creates, migrates and drops its own isolated schema.
- Admin `analysis-settings.test.tsx`: **1 passed**.
- Admin `analysis-settings-history.test.tsx`: **3 passed** (on-demand pagination,
  invalid repeated-page recovery, and stale request cancellation).
- Admin TypeScript and changed-file ESLint: passed.
- Changed Python modules: Ruff, formatting, and targeted mypy passed.
- `git diff --check`: passed.

These are local contract checks. The complete v0.2 report/language/engine/progress
release and its visual, staging and production acceptance remain separate work;
this document does not claim those features are deployed.
