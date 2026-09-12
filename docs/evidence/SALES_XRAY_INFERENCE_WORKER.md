# Durable inference follow-on — 13 September 2026

This follows frozen local integration `1e8b1596da141bbc81b2a968167313a095681e9c`.
It is a separate implementation slice. It does not activate hosted uploads,
provider settings, a production worker, or a public application.

## Admission and effect

The internal `ConversationInference` service accepts only a separately issued
quote tied to the current owner/session/tenant, recording hash and revision,
provider, model, request digest, recipe, measured duration, privacy and permission.
It requires an immutable owner acceptance. Permission to keep a recording locally
cannot authorize an external provider request.

The first durable provider stage is C2 transcription. It uses the verified C0/C1
source and duration, reserves an explicit minute allowance and shared budget, and
enqueues exactly `conversation.infer_provider.v1` with only a version and run ID.
There is no implicit minute grant or quote-issuing authority in this service.
Each recording/checkpoint input has one canonical task. Additional clicks or
coaching-profile changes cannot enqueue another transcription for that input.

The worker commits its dispatch marker and in-flight reservation before the
effect. It then holds the existing recovery-generation and canonical authority
locks across a bounded broker invocation. A dispatch with no durable result is
held for reconciliation, never silently resent. Extra queue claims permit an
acknowledgement after a committed receipt; they do not authorize another provider
attempt. The local idempotency key is not a claim that the provider supports
upstream request deduplication.

The provider response remains an untouched private object. A validated normalized
transcript, C2 checkpoint, non-content receipt and completed run commit together.
An HTTP success does not establish an invoice: actual cost remains unknown and
the reservation remains held until explicit reconciliation. No new real recording
was sent to any provider while developing this slice.

## Process boundary and content

`ProcessInferenceBroker` sends bounded metadata and exact bytes over private pipes
to one fixed Python child. Only that child obtains the selected provider credential
from an approved external launcher. Infisical references are provider-specific;
imports/expansion and noisy output are disabled. The parent excludes provider and
database credentials from its child environment. After selecting its credential,
the child removes unrelated environment entries.

Windows launches suspended, attaches a kill-on-close Job Object and resumes the
process before sending input. Cleanup joins the process, descendants and pipe
reader, including repeated cancellation. Windows HANDLE APIs have explicit ctypes
signatures. This implementation uses `NtResumeProcess` and has Windows test receipts;
the POSIX process-group branch still needs execution on the release host.

Native raw response hashes and parsed content must agree. Normalized output cannot
claim a different raw response as its source. Provider request IDs may begin with
digits. C2 cannot carry a coaching profile; C4 fact envelopes and C5 qualitative
coaching envelopes have separate input and profile boundaries. The C4/C5 adapters
are pure request/result adapters here, not a composed durable reporting pipeline.

Deletion uses the same storage fence and includes the exact provider-response
objects belonging to canonical inference tasks. It erases task input and C2
content while retaining non-content identifiers, hashes and audit history.
Migration 0031 also prevents reviewer metadata/proposal replacement or row deletion;
only a one-way content erasure is permitted. Migration 0030 is unchanged.

## Verification and remaining integration

External receipts live under
`D:/Projects/authority-closers-release-transfer/2026-09-13-sales-xray/receipts/`.

- `inference-domain-unit.xml`: 337 passing conversation unit cases, including the
  task and broker tests. This overlaps focused receipts; do not add those counts.
- `inference-existing-worker-isolated.xml`: eight passing native/PostgreSQL worker
  cases using distinct disposable schemas and private storage per test.
- `inference-durable-postgresql.xml`: ten passing durable C2 PostgreSQL cases:
  exact consent and source/provider/model/permission rejection; one task/job and
  reservation for duplicate inputs; raw/C2 persistence; forced crash after receipt
  commit with acknowledgement-only recovery; failure/timeout holds; deletion before
  dispatch and after a successful result; immutable reviewer history and erasure.
- `broker-subprocess.xml`: 16 passing focused cases, including real Windows parent
  and descendant cleanup, repeated cancellation and input-write timeout. These are
  included in the 337 unit cases above, not additional independent coverage.
- `inference-final-ruff.txt` and `inference-final-mypy.txt`: scoped static checks
  passed, including eight application/worker/adapter Python modules for mypy.
- `inference-migration-v1.xml`: populated migration/model parity for initial 0031.
  Subsequent review-history trigger coverage is recorded in the durable PG suite.
- `inference-existing-regression-v4.xml`: 23 passing and two failed cases before
  fixing shared-queue leakage in the worker test harness. The isolated worker
  receipt above supersedes those worker failures. Earlier setup failures and
  fixture-clock failures remain preserved in the prior numbered receipts.

The runtime contract still needs a hosted quote/allowance authority, current admin
configuration activation, canonical real-provider receipt/cost reconciliation,
durable C3–C6 orchestration, HTTP/client capability wiring, and hosted private-media
composition. Existing local/test HTTP restrictions remain in place. Complete
staging/production status belongs to the coordinated release receipts, not this
document or a successful synthetic broker test.
