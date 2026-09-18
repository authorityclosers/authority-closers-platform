# Sales Xray execution controls

An authenticated AC control account can pause or resume new inference from Admin > Sales Xray > Provider settings. The command is bound to the configured operations tenant and environment. Existing verified identity, active session, membership and Admin-host/origin checks remain required. Saving a change appends revisioned history, an idempotent command receipt and the canonical audit event; it does not edit job, budget, recording or report history.

The pause is checked at quote approval, stage acceptance/start, worker claim and the final durable dispatch marker. The final check and the Admin write serialize on a short transaction-scoped advisory lock. A marker committed before pause is already-started work and may finish. Pause never refunds or erases costs. Revocation, consent, source binding, provider configuration, recovery generation and job lease checks still apply.

Integration owner must add `await self.authority.require_execution_enabled(self.app)` immediately after current admission in `ProcessingPlanCoordinator.accept`. That file belongs to the continuation lane and is intentionally not edited in this leaf. The stage and final worker fences already protect external execution.

Public availability returns only a boolean. It reflects an explicit pause or exhaustion/overrun of the current release-pinned durable budget. The client displays a contact message and retains saved-call/report access. Admin shows the real ledger's available, reserved/held, settled and uncertain amounts, with warnings at 80% and 90% committed. A reservation is not an invoice. Missing budget evidence is shown as unavailable, never as a new allowance.

Migration `20260914_0041`, based on `0040`, adds `conversation_execution_controls` with a database UPDATE/DELETE rejection trigger. All three backup/restore parity controllers use contract v21 and the 0040→0041 rehearsal preserves existing rows.

## Verified locally

- Focused budget and backup/restore checks: 1,227 passed; two explicit integration skips (Docker unavailable and approved restore dump not supplied).
- HTTP availability/schema checks: seven passed, including exhausted and overrun budgets, unsupported hosts/query scope and unauthenticated Admin access.
- React interaction checks: three Admin tests and two public-client tests passed.
- Both app TypeScript checks passed; changed frontend files passed ESLint; changed Python files passed Ruff lint/format; Git whitespace check passed.
- Actual disposable PostgreSQL migration, history/auth/idempotency, queued-old-configuration pause and retained-report scenarios passed. The release handoff receipt records the final rerun and concurrent-other-admin result.

JUnit files live in `D:/AC-authority-closers-release-audit/`: `execution-control-unit-parity.junit.xml`, `execution-control-http.junit.xml`, `execution-controls-ui.junit.xml`, `execution-availability-ui.junit.xml` and `sales-execution-control-pg.junit.xml`. This leaf made no provider calls, paid purchases or staging/production mutations. The native C1 fixtures used the existing verified AudioAtlas binary and synthetic one-second audio.

## Operational limits

Pause takes effect when its command commits. Current identity locks may delay an Admin command when that Admin is also the owner of the recording already being processed; those existing authority locks are preserved. A different authorized Admin can operate independently. The durable dispatch fence is not held over the provider request.

A pause racing after claim but before dispatch leaves the queued job and reservations intact. Resume uses normal lease recovery; it may wait for the existing lease to expire. Already-started work may return a report or require reconciliation under the existing pipeline rules. Live authenticated browser proof and deployment belong to the release owner; these local tests are not staging or production evidence.
