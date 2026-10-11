# Strike C: bounded recording-import admission

The owner's AUT-1676 inbox request replaces tenant-wide minute-based admission.
A never-uploaded or failed source used to block every later batch until its
minute event changed. This change admits one active local source per uploader
across that uploader's batches. A batch therefore cannot multiply its uploader's
local capacity, and another uploader or an ordinary upload remains independent.

Only the latest local run of the current retained recording/generation counts,
with the organisation's processing principal, an active local job and valid
source lease or exact owner continuation. The deadline is fixed at one hour
from that local run's creation. Completed/failed/cancelled local work, held or
terminal jobs, absent uploads and provider-only processing claim no local slot.
Minute journals do not determine admission. Existing tenant transaction locking,
source/member/consent grants, ledger settlement and safe provider retry remain.

Batch progress adds canonical local_state, plan_state and terminal_state. The
CLI advances the next local upload while an earlier accepted plan runs, waits
60–300 seconds on temporary capacity/service conflicts, and reuses the same
source/index and content-derived plan/acceptance keys. Permanent media/allowance
refusals and held/failed calls receive identifier-only attention receipts; later
items continue. Ordinary authentication, target, consent and unrecognised
conflicts stop writes. Upload bytes are reopened and rehashed on each attempt.
Lost upload/acceptance responses require canonical batch read-back before a new
write. No implicit safe retry or uncertain-provider reconciliation is introduced.

Verification: 45 focused cases pass: 37 operator transport cases, one
comprehensive PostgreSQL admission state/race/continuation regression and seven
existing native/authority/delivered-report PostgreSQL cases. The existing proof
includes worker/scheduler restarts, safe retry races and exactly one delivered
minute settlement across replays. Four changed sources pass targeted mypy;
changed-file Ruff, formatting and whitespace checks pass. Test input is
fictional and PostgreSQL uses a disposable loopback schema. The
prior exact-query reproduction and source receipts are retained outside Git in
/home/acdev/strikes/1676/admission-redesign-readonly-repro.json and the strike
notes. This source session does not mutate hosted data, deploy or merge.

To check on dev: resume a confirmed ordinary member-owned batch with its exact
original manifest and explicit rights/plan consent. A failed/held item stays
visible; the next recording can upload. During C0/C1 the same uploader receives
a temporary capacity conflict; after C1 completes the next source can upload
while the previous report continues. Check the ordinary call for its eventual
report/failed status; a finished upload does not prove report delivery. Claude
retains the named hosted import operation and H owns uncertain C2 reconciliation.
