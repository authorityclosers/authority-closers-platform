# Durable facts and coaching — 13 September 2026

This slice follows `952aa8123bd7432aa5d85cabeedda5788ad74db4` and extends the
same internal provider worker through C4/C5 and an owner-only C6 draft. It does
not change migrations 0030/0031 or activate hosted provider processing.

## What now connects

The caller selects an existing canonical transcript checkpoint. Source, owner,
recording revision, native response receipt and the local measurement checkpoint
must agree. C3 records source-clock support and uncertainty. The provider-native
clock is not certified as the decoded AudioAtlas clock; physical speaker-channel
attribution remains unverified. C3 does not invent acoustic measurements or sales
judgments from that uncertainty.

C4 splits the full transcript into bounded, complete-segment requests. Each chunk
has its own exact input digest, accepted provider quote, reservation, immutable
task and raw response. Coaching waits for every chunk. The complete fact checkpoint
binds their manifests and rejects missing, overlapping, duplicate, foreign-source
or mismatched-clock evidence. Literal quotes and timings are validated again when
fact packets are merged.

C5 stores the exact profile snapshot and selected model with the request. It takes
the complete facts, never rereads audio, and cannot change C0–C4. C6 creates the
private draft presentation in the same transaction as the successful C5 result.
It is an AI draft, not Dipak adjudication, scientific validation, official scoring
or public publication. The 95 actual / 100 declared weight discrepancy is held.

All external stages use the existing separate bounded broker and durable dispatch
marker. An acknowledgement failure after a committed response does not repeat
inference or create another report. Unknown provider outcomes and actual costs
remain held for reconciliation. Text-stage minute consumption is the explicit
server-issued quote value; this slice invents no per-stage grants or tariffs.

## Saved report behavior

The existing owner-only report API reads both legacy local imports and canonical
worker drafts using distinct proof schemas. Worker drafts must resolve to their
actual provider jobs, exact quote routes, input hashes, native response references,
source/fact/profile/presentation checkpoints and retained profile snapshot. A
missing current default profile cannot invalidate a durable historical profile.
Invalid evidence is not advertised as an available report in history.

The transcript can be read after C2 finishes, before coaching is ready. Deleting
the recording erases all source/features/provider-response objects, C0–C6 content,
task inputs and report/profile/transcript JSON while keeping non-content audit
history. Changing the profile leaves the previous draft available as its own
version and reuses the prior source, measurements, transcript and facts.

## Evidence and scope

Machine-readable receipts are outside Git under
`D:/Projects/authority-closers-release-transfer/2026-09-13-sales-xray/receipts/`.
The final receipt manifest records counts, content hashes and the frozen commits.

- `reporting-domain-unit-v2.xml`: 362 passed, including the alignment, worker-stage
  and fact-merge cases; focused unit receipts overlap this total.
- `reporting-reviewed-pg.xml`: 14 passed, covering seven existing report/HTTP cases
  and seven reporting flow/guard cases. `reporting-readback-final.xml` reruns the
  two full-flow cases with extra missing-default-profile and corrupt-receipt
  checks: two passed. These are repeated cases, not two additional cases.
- `reporting-mypy-v2.txt`: six source modules passed. `reporting-final-ruff-v2.txt`:
  changed source and tests, including browser harness, passed.
- `browser-durable-worker-final2.xml`: one real Chromium/TCP browser case passed
  in 53.73 seconds. The adjacent `browser-durable-worker-final2/` directory holds
  screenshots and `durable-authenticated-browser.json`: AC cookie authentication,
  worker-generated draft, transcript/audio range/seek, 390px layout and reload
  without provider rerun. It also checks a new local-only upload. No API mocks or
  external browser requests were used. Synthetic provider responses were injected
  into the bounded worker; Google login, real-provider inference and production
  runtime were not exercised. The first fixture needed its required caller-owned
  report-read transaction; no runtime authorization rule was weakened.

- Full-flow PostgreSQL cases cover single- and multi-chunk calls, exact model
  quote rejection, all seven checkpoint stages, transcript-before-coaching,
  duplicate-click reuse, profile-change reuse, private report reads and erasure.
- Additional PostgreSQL cases cover missing/foreign/incomplete facts, current
  session/quote revocation before dispatch, malformed coaching responses, and
  report/receipt commit followed by an acknowledgement crash.
- Alignment and worker-stage unit cases cover explicit clock uncertainty and
  ensure text stages do not load source audio.
- The first full-flow attempt exposed `source_rate` versus `source_sample_rate`
  in the new C3 adapter. The adapter and fixture were fixed against actual native
  metadata. The failed receipt remains preserved.
- An initial unit run used the default temporary directory under an ancestor Git
  repository. Private storage correctly refused it. Its failed receipt is kept;
  subsequent runs use isolated storage outside Git.

No new real recording was sent to a provider during this slice. All generated
test reports use synthetic provider responses. A successful structural workflow
is not proof that a model gives correct sales advice.

## Still required for the requested product

Connect the hosted quote/allowance authority, admin configuration activation,
external provider-specific secret references and provider cost reconciliation;
compose the private hosted storage/worker runtime; connect automatic stage
progression to the authenticated upload UI; finish review-feed identity mapping,
quality calibration and controlled promotion. Execute Linux process isolation,
capacity, canary/rollback and release checks through the release coordinator.
The existing upload UI still starts local measurements only. An internal durable
reporting service does not by itself make a public upload-to-report product live.
