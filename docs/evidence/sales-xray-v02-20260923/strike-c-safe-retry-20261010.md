# AUT-1676: source-bound retries, recovery and customer minutes

The private owner API prepares a bounded successor with an idempotency key.
A provider successor uses a fresh checkpoint replicate and requires new plan
acceptance. Original task intent, dispatch marker, provider response/evidence,
claim counts and provider-cost reservations remain intact. Existing provider
request/cost caps still apply: a one-send source refuses retry atomically with
no extra customer reservation or quote. Transport eligibility is not permission
to dispatch, and an uncertain cost is not proof that the provider did no work.

Local failures release customer minutes immediately. Pre-plan work expires at
the upload lease or existing owner-continuation deadline; a live quoted/accepted
plan owns its own later immutable deadline. An orphan usage without a lease has
the same one-hour technical budget. Recovery skips live locks/leases, respects
the recovery generation and stops released work without clearing its effect
evidence. Audit failure rolls the terminal transition back. Owner local retries
reuse only identical current private upload terms, have zero external-provider
cost/entitlement and are limited to three local attempts. Provider retries are
limited to three attempts for the unchanged checkpoint input, subject to the
stricter existing source/provider caps.

Usage-row and owner-admission locks serialize release, renewed admission and
delivery. A renewed reservation is bound to its fresh plan so a late old worker
cannot capture it. A valid source-bound C6 draft and the single delivered receipt
commit together. Two tabs with one key recover one durable result; another key
cannot create competing live local work or a second quoted provider plan.
Same-timestamp local jobs use durable job creation order, with a separate guard
against any already queued/working local job.
The expiry case also creates a new local worker, claims the successor and
checks its real worker admission at the resumed clock after the original source
lease expired. The existing owner continuation admits the exact fresh run and
quote; no native execution or provider call is fabricated by that assertion.

Progress exposes queued, working, retrying, failed or done from persisted facts,
plus the customer minute outcome and owner retry availability. Done requires a
validated saved report. Retry availability uses the existing strict ownership
port; organisation read permission never grants retry. A real admin-cookie
PostgreSQL case can read another owner's failure, receives retry_available=false
and a 404 from retry, while the original owner can prepare its successor.
The small existing status component consumes those
fields and prepares/reviews/accepts the safe retry. Network waits end after 20s;
ambiguous responses preserve the command key for reconciliation. Error copy
uses the existing corner notice cards. No page/layout or report rendering edits.

The watchdog command is:

```sh
uv run python -m ac_platform.conversation_intelligence.run_budget_cli
```

Use the service's existing runtime-injected AC_DATABASE_URL; do not paste a DSN
into an issue, log or shell command. The check has a read-only transaction,
10-second connection/pool/query bounds and emits identifiers only. Exit 0 means
clean, 1 means overdue quoted/active plans, abandoned reservations or released
unfinished runs, and 2 means the check was unavailable. This session did not
install a scheduled alarm or invoke it against staging/production.

Focused validation: 22 disposable-PostgreSQL checks across safe C2/C4/C5
successors, real owner HTTP, local retries, released-run recovery, read-only CLI,
minute journal and plan budgets; 120 processing/inference/reporting/progress/
retry unit checks; 77 frontend contract/status/action checks. Targeted mypy
(15 modules), Ruff, frontend typecheck and changed-file ESLint passed. Full-shaped
synthetic signals and explicit fictional native validation receipts isolate the
retry/charging boundary; these do not prove native execution or report quality.
Earlier local native setup failures remain recorded in the journal-contract
evidence. Browser/CI/deployed verification is recorded separately as it finishes.

The PR remains sensitive (customer accounting, migration and backup parity),
requiring CTO/CEO review under the owner strike rules. No manual merge,
deployment, staging/production data write, provider setting change or new paid
credential was performed.
