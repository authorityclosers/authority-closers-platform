# Guest submission adapter evidence — 14 September 2026

Implemented against combined source `529c389cbb289fdaefbb5a4da04fb6b2480f7823`.
The Sales HTTP/source/report consumer and actual app/settings composition are
added here. Root owns shared guest processing, identity/migration, provider
policy, credential/widget provisioning and release.

## Tested here

- Native/source regression group: **87 passed, 1 skipped** (Windows has no POSIX
  ownership semantics). Includes **22 source-preflight cases**, actual one-second
  WAV → ffmpeg → unchanged AudioAtlas native executable, resampling provenance,
  full original hash, decoded sample count, changed source, forged duration,
  corrupted features and mismatched receipt rejection.
- Actual PostgreSQL plus HTTP/cookie boundary: **4 passed** in 23.48 seconds. Uses FastAPI's
  in-process ASGI transport, not a browser/TCP connection. Covers bounded original
  upload, retry with one usage/run, native local worker, private range playback,
  cross-guest denial, account claim, expired-lease access, queued and completed
  erasure, origin/host/query/duplicate-cookie/consent/source tampering.
- A PostgreSQL test reaches C6 through the actual plan scheduler and
  inference worker with an explicitly configured **synthetic** ElevenLabs/Gemini
  broker. It verifies the detailed overview, matching transcript/source revision,
  retained reads after expiry and acquisition settlement before any report GET.
- Actual `create_app` composition accepts a twelve-second WAV larger than one
  MiB, reserves its measured twelve seconds once, and rejects an oversized
  neighboring JSON request with 413. Its socket adapter is replaced only in the
  test with the real offline decoder; it does not claim a live Unix socket.
- Startup/credential reference unit tests: **8 passed**. Missing configuration
  leaves core routes available; only one valid narrow external challenge file
  is accepted, with redacted failures.
- Existing app composition, settings and streaming video regression tests:
  **233 passed**. This checks the shared startup/request-limiter change against
  the existing platform behavior.
- Scoped mypy: **8 source files passed**. Ruff passes for all 12 changed Python
  source/test files, including formatting.

Portable JUnit/log receipts and their hashes are in
`docs/evidence/guest-submission-adapter-20260914/receipt-index.json`.

## Repairs made during verification

- The first unit run had nine temporary-directory setup errors because the new
  external receipt parent was absent. A new preserved receipt directory corrected
  the harness; this was not an implementation pass.
- Actual native preflight found Windows CRLF in `checkpoint.json`, which failed
  the existing canonical native contract. `signals.py` now writes explicit LF;
  the validation boundary remains unchanged.
- The first full-provider fixture run consumed an earlier test's undrained
  deletion job and correctly refused transcription before C1. The first test now
  also executes and proves complete erasure; the full three-test run passes.

## Limits and release status

No new external provider request, credential access, real-call transfer, SSH,
deployment or DNS operation occurred in this packet. Synthetic broker coverage
does not claim provider quality, allowance or live inference.

Actual app wiring is implemented and opt-in. A frontend consumer and release
configuration/provisioning remain required.
Current activation still needs the root-owned approved per-upload/source provider
policy; the adapter does not create it. Native preflight repeats local C1 before
canonical publication and needs hosted timeout/capacity verification. No actual
browser/TCP, staging or production test is claimed for these new guest routes.

Dipak's overview itself remains the earlier completed UI packet, with its own
compiled-browser/mobile/print evidence and private owner report preview. This
adapter connects that same validated overview to guest ownership; it does not
replace the LMS or promote official numeric scoring.
