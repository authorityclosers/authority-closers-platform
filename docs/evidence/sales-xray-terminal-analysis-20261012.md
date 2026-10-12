# Sales Xray terminal-analysis repair: local C1 slice

This is a bounded worker repair within existing Strike H / AUT-1801. It does not
establish the complete customer-settlement, retry, staging or release acceptance.

## Authority and source

- Workbench baseline: `0c26d4fb00d14c2386fe36b8de84db1188cbb199`, `dev/live`.
- Root handoff: CTO revision `05e3fbef-c7ea-44c1-97dc-960a4c8f1a4d`, CEO decision
  `4e3dccb9-8477-4899-835e-054f906b1dd7`, customer-settlement revision
  `144e03d4-bec3-47fd-a0db-ab0cb8bbf7f1`, terminal decision revision
  `70a2f290-4847-430b-8a5f-ea4951c7f4b9`. All four handoff documents matched
  their manifest byte/hash pins before implementation.
- Private admission receipt: `1801/terminal-repair-admission-20261012.json`,
  SHA256 `fb98a58e6fc2d60bf6bc883a1b787afe95646b6ad304c94e2559296dac60057c`.
- Controlled intake: exact manifest IDs, Master Index and six required sources
  first, then fourteen slice specifications and UXA/GOV-AUD. All 23 decoded
  source bodies and their saved byte/hash pins are retained privately in
  `1801/handoffs/terminal-controlled-sources-20261012/intake.json`, SHA256
  `f6767a5007eef44746cb864170391acc28eebabe1202fdbb7c066a093719b076`.
- Applied controls: BRD Q073 preserves audit-critical history; AC-IMP-03 ENG-G02
  keeps durable work separate from events, ENG-G10 requires contract proof and
  UX-G05 preserves distinct unavailable/reconciliation states. No provider or
  scoring activation follows from this source intake.

## Reproduced defect and repair

A fictional expired local C1 claim at its attempt ceiling becomes dead-lettered
through the existing queue policy. Before this change, its persisted run remains
queued with no terminal timestamp. The original reproduction failed on precisely
that assertion: **1 failed in 11.64 seconds**.

The local worker now reconciles at most one matching dead-lettered C1 run per
claim transaction. Current tenant/person/source/quote/generation and recipe bind
the candidate. Existing queue deadlines and retry backoff determine exhaustion;
no new inactivity threshold or guessed stage deadline is introduced. Completed,
cancelled, deleting, changed-source and retained-C1 work remains intact.

Uncontended job/run/recording locks fence publication and stale workers. The same
transaction commits the failed run, completion timestamp and one append-only
`conversation.local_job_recovery_required` event. An audit error rolls back the
entire transition. Repeat and concurrent sweeps preserve the first timestamp and
emit one event. This event is internal failure evidence; paired minute/budget
snapshots and dispatch/receipt/claim evidence remain unchanged.

The existing authorized run read and stage projection can expose the committed
failed state and finish time. Neither this event nor that state says minutes were
returned. Canonical customer release remains a separate unimplemented slice.

## Verification

Final database suite: **21 passed in 19.66 seconds**, no skips, under ordinary
`ac-heavy timeout 180 uv run pytest
tests/database/test_conversation_local_terminal_recovery_postgresql.py -q -x`.
Ruff lint and format checks, focused worker mypy and the required
`uv run python -c "import ac_platform.http"` each exited 0.
The runner regression suite is recorded separately in the private packet.

The 21 cases cover exhausted/permanent jobs, a committed local execution marker,
future backoff, live leases, completed/cancelled/deleting work, changed
generation, wrong run/kind/quote/tenant/source/revision/owner, a malformed
generation, a retained C1 checkpoint, lock contention, audit rollback and
concurrent duplicate sweeps. Recovered cases verify unchanged paired accounts,
the audit chain, authorized run read and canonical finish time, stale lease
rejection, one event and stable completion time on replay.

Exact tested worker/test SHA256 pins:

- `packages/python/ac_platform/conversation_intelligence/worker.py`: `bf244a3dea6248606ed833b3ca8c6e1bd63367c94590ec14de76942da051b125`.
- `tests/database/test_conversation_local_terminal_recovery_postgresql.py`: `5e91e1583398411bf5d7fb5879923b104847e622f4b6fab0b40d7b4a69788124`.

 A malformed string generation initially blocked a later healthy candidate. The
query now checks the JSON value before removing its type, so that row is refused
without starving other work. This failure and initial collection/fixture failures are
retained privately and are not counted as passing evidence. In particular, an
attempt to mutate a fictional quote was refused by the existing immutable-history
trigger; corrected cases use separate unaccepted quotes and preserve the original.

## Preview and remaining integration

Before implementation, dev API readiness returned HTTP 200 with source
`a5d45b4ca85a16858143846be70495a91ffdc5e2`; the populated Report fixture returned
HTTP 200 at <http://127.0.0.1:3026/review-fixture/report/story>. This is shared-dev
availability and a fictional preview, not an authenticated failed-call journey.

Root received the finite shared financial/schema and new writer/test sequencing
request through the existing coordinator inbox. Original cumulative and guarded
preparatory patches, protected-file handover and a reserved forward migration are
still required before authoring that slice. Imports, analysis UI, Report,
Document, Coaching and QA remain with their existing owners.

The full 503/503/success, permanent refusal, ambiguous timeout, provider receipt,
customer settlement/publication races, authenticated idempotent successor and
personal/organisation/guest parity packet remains open. Existing approved staging
authentication is unavailable in this seat. No real provider call, financial or
schema write, historical replay, manual deployment, release or promotion is
performed. The v0.41.0 hold and independent v8/SVAL/timing prerequisites remain.

## Committed source and automatic dev read-back

Code commit: `1af60b24c4183a3b530bd749e6d39b17f4a1eab9`. Final runner
regressions also passed: **17 passed in 0.81 seconds**, bringing focused proof to
38 cases. Readiness HTTP 200 serves that exact commit. The existing automatic
deploy log records successful smoke checks, API health and worker pickup at
15:55:52 UTC. This establishes service pickup, not a failed-call or financial
journey. The single final partial packet is retained privately as
`1801/terminal-local-c1-final-packet-20261012.json`; the earlier packet is preserved.

## Admitted settlement source preparation — 12 October continuation

Root run `7b48b475-c42b-434c-8fa3-be3cbca0093c` admits twenty exact source/test
paths and reserves `20261012_0088` after `20261011_0087`. The admission explicitly
sets `schema_apply_authorized=false`. Since a migration commit automatically
applies dev schema, the migration and live writer enablement remain pending the
existing Root decision. No deploy trigger or service was changed.

All three recovered original artifacts, four decision documents and 23 retained
controlled-source byte pins were verified. The original cumulative patch was
applied once, followed by the guarded loader delta. Historical checks are kept
separate from this continuation's executed checks.

The prepared `customer_terminal_settlement.py` writer rechecks exact persisted
processing/source/usage/run/event facts. In one transaction it appends a truthful
zero-charge `terminal_failure` acquisition settlement, releases the existing
Report minute journal, binds typed terminal evidence into both provider account
snapshots, and appends audit. It creates no grant or no-work receipt. Provider
state, original dispatch/uncertainty evidence and cost exposure are preserved;
late provider cost reconciliation keeps customer usage at zero. Identical replay
is a no-op, a changed receipt conflicts, and old failure replay cannot release a
new authenticated retry reservation. No runtime worker or HTTP route calls this
writer in this slice.

The current source already has the canonical Report minute journal (0080). This
writer reuses it; it does not introduce a second journal. The bounded adapter
accepts the existing exact provider-job-recovery event only. Ordinary failure,
terminal plans, subsequent failed retries and C1 customer settlement need their
own source-bound integration; they are not silently treated as this event.

A real two-transaction test reproduced a usage/run lock inversion during draft
publication. The recovery loader now refuses a contended usage row with
`SKIP LOCKED`, allowing the winning transaction to finish without deadlock.
Current quote and execution-permission objects are matched to persisted rows
before paired account updates. Budget locks precede minute locks.

Final focused run: **186 passed in 98.21 seconds**, no skips. It covers the
receipt/snapshot/entitlement suites, guarded candidate, twelve writer cases,
two migration proofs and focused existing acquisition/identity regressions.
Original C1's 21 database and 17 runner checks are retained without reruns.
The private final packet supplies exact commands, exits and source/log hashes.

The publication proof has a deliberate limit: it uses a directly persisted
fictional draft and the actual Report minute journal, without validated C6 or an
authorized readable report. Failure wins sequentially; publication wins in a
concurrent race. This establishes the bounded writer's rollback/serialization,
not full pipeline delivery acceptance. Authenticated retry proof covers the
existing reservation intent only; it does not dispatch a successor.

Migration proof rehearses constraint reversal without failure history, checks
zero-charge and append-only enforcement, and refuses reversal once failure
history exists. Physical PostgreSQL template snapshot/restore retains exact
settlement, journal, paired snapshots, audit, constraints and triggers on owned
disposable databases. It is not hosted backup-script execution.

Full fictional 503/503/success, permanent 503, pre/post-send timeout, validated C6
publication race and authenticated safe successor remain required. Existing
approved authenticated staging context remains unavailable; the same-call,
person, tenant and tested-build API/UI journey is unperformed. Root owns the
existing operator context and automatic-dev schema decision. Independent CTO
then CEO exact-source review, release-engine version and What's new remain
required. No provider call, scoring activation, historical data apply, staging
or production mutation, manual deployment, release or promotion was performed.

Prepared source commits: `3f7207a3` and `0597e0ae`. Final Ruff/format/focused
six-file mypy/API import/diff guards each exited 0. Six schema/writer proof paths
remain uncommitted pending Root automatic-dev apply admission. Source-bound
packet SHA256: `71ad1d8c7a72038069c705632c467b9d399d6d0d26765b2400fecb7593921975`; private source-only
patch SHA256: `a514d5630b0fcaf0a02694fc4cb3bf2978da270354f6238e6c0f7279ff9bd6bb`.
The concrete packet was delivered to the existing Root/coordinator INBOX route.
