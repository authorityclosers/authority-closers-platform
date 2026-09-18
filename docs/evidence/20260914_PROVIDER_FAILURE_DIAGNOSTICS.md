# Sales Xray provider failure diagnostics - 2026-09-14

The actual staging C4 call received a provider response but failed evidence validation (`report_evidence_quote_mismatch`). The durable worker replaced the reason with `conversation_provider_execution_unresolved`, so operators could not distinguish an invalid quote from transport failure. Later canonical deletion erased this test call; no deleted data is restored by this change.

This patch records a small allowlist of typed validation reasons in the existing job failure field. Unknown exception text never enters the field, and timeout/storage errors use fixed categories. Job dispatch markers, uncertain budget holds, lease fencing and retry policy are unchanged. Cancellation still completes the failure acknowledgement and propagates.

Validation on the isolated c437-based worktree:
- 15 focused diagnostics and worker-stage tests passed.
- Ruff check and format check passed.
- Mypy for inference_worker.py passed.
- Independent review pending.
- Staging/production deployment pending. This patch alone does not fix the C4 response contract or create a report.
