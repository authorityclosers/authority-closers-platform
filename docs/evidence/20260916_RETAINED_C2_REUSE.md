# Retained C2 reuse for exact duplicate uploads

## Finding

The guest recording could not progress because the original Deepgram C2
response was durably retained, but its one out-of-order word timestamp failed
the then-current strict ordering validator. The original provider job was
therefore held for reconciliation, and the later byte-identical upload was
correctly refused by the hosted allowance guard because it had no independent
provider reservation.

## Implemented boundary

The acquisition processing-plan path now has a bounded retained-C2 reuse
branch. After the owner accepts a current exact plan, it may reuse a source
response only when all of these are independently verified:

- same tenant, person, source digest, source revision and generation;
- live source recording permission and retention;
- the current C2 route, recipe, configuration and duration;
- the original task, run, quote, dispatch marker and canonical provider receipt;
- the private response blob hash and the current C2 validator.

The original task, job, receipt, provider reservation and ledger history are
not edited. The target receives its own immutable C2 checkpoint, task, logical
completed job and derived zero-cost quote; the target job has no provider
dispatch marker. Its receipt explicitly records the source recording and source
run and reports zero new provider calls. The raw response is not copied into
the target object namespace. Any failed proof stops with a conflict instead of
silently falling back to a new provider request.

## Verification status

The retained receipt and source-blob marker contracts are covered by unit
tests. The PostgreSQL tests
`test_duplicate_upload_reuses_retained_c2_without_a_second_asr_call` and
`test_guest_duplicate_upload_reuses_uncertain_retained_c2_without_provider_call`
cover the duplicate-upload C2→C6 path. The guest test uses the public HTTP
submission flow and an uncertain/provider-returned source fixture, then checks
that the original task, job, receipt, checkpoint, plan and allowance snapshots
remain unchanged while the target report is produced.

This change has not been deployed and does not claim production report
success. The end-to-end PostgreSQL proof requires the repository's explicit
loopback test URL; it was not available in the local verification environment.

## Safe release verification

After deploying the immutable commit, generate a fresh plan for the affected
upload if the displayed plan is expired, explicitly accept the exact plan, and
poll the normal submission progress/report endpoints. Confirm the target C2
run reports `provider_calls: 0`, the target C4/C5 stages use only their
approved routes, and the report endpoint returns a draft report with human
approval still false. Separately confirm the original uncertain C2 receipt and
reservation are unchanged.
