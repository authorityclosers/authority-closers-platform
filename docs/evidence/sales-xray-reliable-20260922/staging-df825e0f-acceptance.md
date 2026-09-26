# Staging df825e0f live acceptance checkpoint

Observed 22 September 2026 UTC / 23 September IST. This supersedes the pending
deployment and short-report statements in `structured-provider-acceptance.md`.
It does not establish long-call or production acceptance.

## Exact release and deployment

- Source: `df825e0f5626e6c70c42d6f08342a185bf69935c`.
- Successful exact-source GitHub runs: application `35774061955`, native
  `35774065817`, web `35774069338`, PR application `35774049513`, control
  `35774049473`.
- Required compiled acquisition browser artifact `10714719987` passes 15
  assertions; ZIP SHA-256
  `20f09988898fdf67fa202b40e056a99e42c5ab705e2c2a838e057c6fec96d3b6`.
  That gate uses deterministic providers and is not live-provider acceptance.
- Application transport artifact `10715847311`, ZIP SHA-256
  `67757099851811b1ddfd725c93b961194bb429e7da2cb911ef9193ca19e4c5e5`.
  Local and VPS copies verified against GitHub and all member checksums.
- API/worker runtime image:
  `sha256:699b22aad076293baaf7baac7c627065bdca7f4ccf4c17812c643f1406c91d78`.
- Native image:
  `sha256:4e356b52f386a8d5d18ac86da0c23ce600737e9dbf831d1fb66d79ce2d59cb08`.
- Web image:
  `sha256:27b0a18ecbe64f36597f3976a58fdb6ad92d056f1cb60f647fc329fa51fd7981`.
- Canonical installer committed receipt:
  `20260922T195301Z-df825e0f5626e6c70c42d6f08342a185bf69935c-r5YxAq.env`.
  Previous release and rollback artifacts retained. Exact API/web healthy,
  workers running with zero restarts, native active at 19:53:21 UTC.
- Existing staging approval, expiry, INR1,000 ceiling and provider revision 3
  carried unchanged. Production remains on
  `f61f15f7fed81ef59cd57f4dd955eb7b2e624427`.

## Live short-call recovery

The previously paused fictional 59.814-second price-objection call was resumed
through the rendered signed-in UI. Quote review was INR418 maximum for a complete
plan; the coordinator reused the existing C2 and C4 work and dispatched only one
new C5 request with an INR22 ceiling. No automatic repair was needed.

The new C5 execution completed, the plan reached C6, and the report returned 200.
The transcript and waveform returned 200; original audio returned 206. The
rendered report correctly identifies early pitching, missed discovery, unresolved
practice/schedule and partner concerns, and no confirmed purchase. It recommends
diagnostic questions before repeating features or requesting payment.

The source moment at 20.960–28.920 seconds quotes the actual package-repetition
utterance. Its Listen button sought and played the saved recording; observed
audio state was playing at 26.356 seconds, duration 59.814 seconds, readyState 4,
with no media error. The report then appeared as ready in Saved calls and reopened
through its stable call link. Canonical server read validation also passed.

Report SHA-256:
`d950652600db16d9fdb4e4bcf5fe2e11ab08b9c1f77be5e76e760ddb125d882b`.
Provider/task receipts and full fictional transcript/report remain in the private
task evidence folder. The earlier unsuccessful executions and their budget holds
were preserved. A completed task does not prove provider billing reconciliation.

## Long-call admission result and correction

The owner accepted the selected fictional 59:57.994 stereo call's terms and
authorized processing within the existing INR1,000 total test ceiling. Its
27.5 MiB upload was measured and rejected with HTTP403 before committing a usage
reservation or dispatching a provider.

Read-only canonical diagnostics show 359 seconds already committed on this
account, leaving 3,241 seconds; the test requires 3,598 seconds. The deployed
staging approval contains **no internal tester accounts**. An earlier assumption
that this account already had a tester exemption was incorrect. No allowance,
identity or budget state was edited to work around that rejection.

The UI incorrectly presented this partial-allowance rejection as a generic access
error. A narrow messaging correction is being tested separately. A staging-only,
account-minutes tester proposal for the existing verified test account is prepared
outside Git and awaits explicit owner approval. It preserves expiry, provider,
retention, customer and production controls. The existing in-app guest session
also has prior usage and was not reset or used to bypass its allowance.

Current recovery testing dispatched ceilings sum to INR89, including three INR1
schema probes and the successful INR22 report retry. This is a conservative
exposure measure, not an invoice total. Long-call live AI quality, full-duration
transcript/evidence, and production acceptance remain unverified.

## Subsequent owner approval

The owner explicitly approved the prepared staging-only tester exemption. Its
issued canonical bundle has SHA-256
`468d14b28572f3fd3e0d5c2b815a5511622d9360e89db29dc51d63088c2e0afa`,
issued at epoch `1790107576`, with unchanged expiry `1790455720` and INR1,000 cap.
Only the existing verified test account's `account_minutes` scope is added.
No analysis-count or session-issuance exemption was added. The exact release
image validates the bundle; a read-only live compatibility check confirms the
existing budget approval remains recognized and all three provider routes remain
approved. Original approval and descriptor bytes are retained. Runtime activation
and the long-call retry still require their own subsequent verification.

## Activated tester and long-call result

The canonical same-source installer committed the approved tester activation at
20:10:19 UTC, receipt
`20260922T201019Z-df825e0f5626e6c70c42d6f08342a185bf69935c-t2dMO7.env`.
Read-only checks verified the exact account now resolves to the named exemption;
its historical 359 seconds remain present. All runtime services were healthy.

The same selected recording and submission then uploaded successfully (202), and
the original source served 206. The native local run completed in 121.7 seconds
and committed C0/C1. The automatically accepted provider plan retained the INR418
maximum. C2 subsequently failed with `conversation_provider_storage_failed` after
dispatch and remains uncertain/dead-letter with its INR22 ceiling held. No
provider receipt was retained. The UI shows transcription paused, without a
confirmed transcript, and does not automatically retry it.

Source inspection establishes a large-response storage defect: `_save_raw` sends
the complete response as one chunk, while private storage rejects chunks larger
than 1 MiB. This is a reproducible code-level failure boundary; the lost live
response's actual byte length is unavailable, so it is not claimed as measured
proof of this exact response. A chunked write regression and preservation of
safe provider-return metadata are being assessed before a new controlled test.

Current dispatched recovery ceilings are INR111, including that uncertain INR22
call. No final long-call transcript/report acceptance or production promotion has
occurred. The original failed attempt and its reservation remain preserved.


## Corrective patch and independent short-report review

Provider responses are now streamed in storage's existing bounded chunks rather
than passing the entire response as one chunk. The response digest and expected
byte count remain checked. The provider-returned receipt is committed before raw
storage, retaining bounded request/response hashes and provider request identity
if storage subsequently fails. Dispatch and global erasure fences remain; this
change does not authorize automatic redispatch or discard the failed attempt.

The partial-trial-allowance rejection now has an exact allowlisted, actionable
message in the API and web client. Unknown access errors remain generic; no
allowance or access policy was changed by this UX correction.

Local validation: 1,142 conversation unit tests pass, with one Windows/POSIX
ownership skip; all 272 web tests and typecheck pass under Node 24.19.0. The
large-response regression exercises real private storage above its 1 MiB chunk
boundary. Database fault-injection and exact-source CI are recorded subsequently.

An independent review of the successful short report checked all 23 source
references with zero quote/timing mismatches and no blocking findings. Modest
omissions and wording limits remain, including limited positive-strength
coverage and wording that could distinguish an offered discount more precisely
from an executed one. This is a bounded pass, not universal AI-quality proof.
The superseding private review JSON SHA-256 is
`1d80190bd4d3457d9fe9ba3149640300ae9022eed503bc0392fe4d8e5f68deec`.
Its zero provider-call/write statement applies only to the read-only export;
the original successful report used one live Gemini request capped at INR22.


The disposable PostgreSQL storage-failure regression passed. It verifies one
provider call, a retained provisional receipt with the returned response hash and
request id, an uncertain reservation, no published C2 checkpoint, and no second
call when the worker restarts. The acquisition PostgreSQL suite passed 16 tests.
Ruff check/format passed across 686 files and mypy passed across 302 source files.
The full inference PostgreSQL module and independent fence review are additional
checks before staging activation; exact-source CI remains required.
