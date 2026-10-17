# Settle stuck provider holds (owner-approved, 17 Oct 2026)

## Why
- Every successful provider call (C2 transcription, C4 facts, C5 coaching) leaves its budget hold "uncertain". The step that turns the provider's usage into a settled cost was never built.
- Each hold keeps the full quoted maximum, about ₹21, while the call really cost ₹1–5.
- On 17 Oct, staging held ₹8,587 of its ₹10,000 cap for about ₹450 of real cost. Production held ₹6,530 for about ₹190. Analyses are refused once a cap fills.

## Owner decision
The owner said "fix this" (17 Oct, laptop cost session): settle the holds at list price from the usage counters the provider returned. The price comes from the planning rates in `admin_pricing`.

## What the script does
- **Basis:** the settlement reference is `list-price-estimate:<pricing ref>:job:<job id>`, so an invoice reconciliation can supersede it later.
- **What gets settled:** only an uncertain hold whose single task's job succeeded with a validated receipt for the same provider and model, and whose estimate fits within the quoted maximum.
- **What stays on hold:** everything else, untouched. The output counts these by reason.
- **Customer minutes:** never change. The settled seconds equal the quoted entitlement.
- **One transaction.** Each budget scope and minute account it touches gets one new revision.
- **Audit:** one event per tenant and scope, `conversation.provider_holds_settled`, naming the approver and the issue.
- **Idempotent:** a settled hold is never planned again.
- **Dry run by default:** it reads without row locks, writes nothing and prints the before/after for every scope.

## Run
1. **Dry run.** Two ways to run it:
   - **Staging or production**, after a release has shipped `provider_hold_settlement`. Pipe the script into the worker container, which reads the worker's own URL file:
     `sudo docker exec -i ac-application-<env>-sales-xray-worker-1 python - --database-url-file /run/ac-sales-xray/database-url --environment <env> --approver "<who, where>" --issue "<ref>" < scripts/data-changes/settle-provider-holds.py`
   - **Dev**, through the injected runtime (`AC_ENVIRONMENT`, `AC_DATABASE_URL`):
     `uv run python scripts/data-changes/settle-provider-holds.py --approver "<who, where>" --issue "<ref>"`
2. Show the owner the dry run.
3. **Production only:** take a snapshot first (`/usr/local/sbin/ac-db-snapshot production`). Pass its SHA-256 as `--production-snapshot-sha256` together with `--apply`.
4. Read back by running the dry run again. It must plan 0 settlements and show the new committed totals.

## Lasting fix
- The worker should settle each hold the same way right after its receipt is recorded, instead of leaving it uncertain.
- The engine rebuild may remove per-call holds altogether, in favour of monthly budgets per organisation.
- Until one of these lands, re-run this script when caps fill.
