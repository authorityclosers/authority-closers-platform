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
