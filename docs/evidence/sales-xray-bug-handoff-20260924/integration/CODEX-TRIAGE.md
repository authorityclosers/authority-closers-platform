# Sales Xray v0.2: handoff decisions and integration queue

Date: 2026-09-24. Owner: main Codex release task.

The owner asked Codex to incorporate the complete Claude handoff and make the six product decisions using the available evidence. This document records those decisions, not a claim that the fixes are deployed.

## Inputs and precedence

- The complete 913-line `HANDOFF.md` in this directory was read, including sections 0–10 and both appendices. SHA-256: `431b29445806866dfa5919ee7399c49f161ce7e35ac6ed17ade73670bc5f2b40`.
- Treat its excerpts, bug labels and implementation suggestions as review inputs. Reproduce each claim against the integrated code before changing it. The handoff contains 35 individual bug IDs and eight proposed PR slices; retain all IDs regardless of the introductory count.
- Existing repository guardrails, controlled product contracts and the owner's explicit account-first requirements remain authoritative. Preserve untracked evidence and existing worktrees. Do not infer a billing guarantee from an HTTP status.
- This is an additive operational addendum to the v0.2 master plan, not a replacement for the report redesign, prospect journeys, batch intake, shared profile, coaching media architecture or provider benchmarking requirements already recorded there.

## Integration first

The following full commits were resolved locally on 24 September:

| Input | Pinned commit | Integration responsibility |
| --- | --- | --- |
| PR 67 diagnostics and browser gate repair | `4bbc2b790431949314d5464fe1973b62d02f87e7` | Integration starting point |
| UI studio / v0.2 intake | `2217d41d5c21aeae64b886d4f17eeb3ee6329b32` | Preserve report navigation, excerpt playback and visual work |
| Google account recovery | `0e0eca6e0cdde19383324fb333d6c965c01d46c0` | Preserve signed completion receipt and recovery tests |
| Avatar transport | `b6f1cf7062d59a52593070972c06ed2d2816baff` | Preserve profile transport changes and tests |

The existing Sales Xray live UI studio task owns the isolated integration worktree and merge branch `codex/sales-xray-v02-integration-20260924`. It merged these exact tips at `7ff3581fc39f616d189c525c2d6b3e23a51e472a`, then committed separate integration corrections. Existing branches were not rebased. No deployment is delegated. Detailed verification and remaining failures are recorded in `EXECUTION-STATUS.md`.

The release owner will review that combined diff before starting new fixes. R1 and R2 must not be reimplemented from the older PR 67 snapshot. Their known fixes already received focused local review on the UI branch; integrated behavior still requires tests. Standalone web and API release identities must both be recorded at deployment.

The previous 52c candidate and its green CI are evidence for that candidate only. They do not establish that the eventual merged candidate passed. Its staging-only packaging adapter remains available, but no new capture or activation is represented as having occurred here.

## Decisions for the six questions

These are the implementation decisions selected under the owner's explicit delegation. Financial invariants remain in force.

### D1. Provider cost, settlement and failed requests

Keep three separate facts: customer allowance consumed, estimated provider cost, and confirmed provider charge. A completed response is not proof of a settled invoice, and an HTTP error is not automatically a zero-cost receipt.

For successful requests, calculate a provisional cost from validated usage and the exact frozen provider/model/rate revision associated with the accepted request. Use integer currency arithmetic, the recorded exchange-rate basis and explicit missing-usage handling. Present it as an estimate unless the provider's accounting contract establishes it as authoritative. Reconcile against provider billing evidence through an append-only, idempotent service. Never rewrite history or silently cap an overrun. Any reduction of a financial hold requires the existing typed settlement/no-charge contract or a separately reviewed extension to it.

For failed requests, classify **outcome certainty**, **retryability**, and **billing certainty** independently. An explicit terminal provider response can establish that the request ended; it does not necessarily establish its charge. A transport timeout, crash after dispatch, or lost response stays uncertain and cannot be automatically replayed.

Google's current Gemini billing documentation expressly states that failed 400 or 500 responses are not charged for tokens, while quota still counts. Apply only a documented provider/status policy with a source revision and an authenticated attempt-bound response; do not generalize this to all 4xx/5xx codes, other providers, or proxy-generated errors. [Gemini billing](https://ai.google.dev/gemini-api/docs/billing).

Groq documents no charge for requests returning server errors and explicitly lists 500, 502 and 503; use an exact reviewed response policy, not a provider-independent regular expression. Its 429 description does not make that billing promise. [Groq errors](https://console.groq.com/docs/errors).

The reviewed [Deepgram errors](https://developers.deepgram.com/docs/errors) and [ElevenLabs errors](https://elevenlabs.io/docs/eleven-api/resources/errors) explain error handling but do not establish a blanket no-charge rule for every 429/5xx response. Unknown billing remains explicit and reserved. No mass historical release based solely on `provider_http_*` is authorized by this decision.

Known completed failures may be retried only when the full additional attempt is covered by the already approved repair/retry budget, even when the original cost still needs reconciliation. Unknown outcomes remain blocked. New attempts and reservations must have separate immutable identities and bounded backoff. Existing per-provider quotas still apply.

### D2. Trial minutes and safe retries

A system retry within the same logical call-analysis lineage must not deduct the call duration from the customer's allowance a second time. Customer admission remains idempotent; a provider's actual second request remains separately auditable and budgeted. A user deliberately asking for a new analysis configuration is a distinct authorized operation, not a disguised automatic retry.

Do not remove a reservation from source-attempt accounting just because a request failed. First define explicit attempt lineage and no-charge/settlement rules. Ordinary accounts retain source limits. Dipak's separately authorized named testing capability may exempt request counts but never project budgets, identity/consent checks, provider throttles or uncertain-dispatch safeguards.

### D3. Truncated report repair

Permit at most one higher-output repair when the accepted plan expressly includes that repair envelope: same source and consent, approved provider/model, maximum tokens and remaining worst-case cost within the quoted plan budget. Use a new attempt identity and retain the truncated result and validation reason.

Existing plans with no such envelope require a fresh quote/acceptance. Do not change a signed plan, model or token limit after acceptance merely because the total looks affordable. Keep the quoted token limit and the actual request limit identical. The Admin setting should override a documented default up to the approved provider ceiling; hidden lower clamps should be removed after reproduction.

### D4. Configuration changes and deadlines

Freeze the accepted source, prompt/validator contract, route/model, pricing basis, ownership, consent and repair budget. An unrelated tester addition, deployment marker change, or cap increase can be compatible, but compatibility must be evaluated field by field. It must not silently adopt a new prompt/model or reset an attempt allowance. Revocation, expired consent, denied retention or an insufficient lowered cap stops new dispatch.

A response from an already authorized dispatch must be durably saved with its original authorization evidence even if a newer policy prevents the next stage. Saving evidence is not permission to publish an invalid report or start another provider call.

Separate time allowed to accept a quote from execution time. Keep the current quote acceptance policy initially. Introduce a configurable execution deadline starting at acceptance, with an initial two-hour upper bound for supported calls, constrained by the earlier consent/retention/authorization expiry. This is a proposed runtime value requiring failure-injection/load verification, not a measured service-level promise. Worker stage deadlines, heartbeats and lease reconciliation must surface a specific delay/hold well before that bound. Do not extend an expired provider authorization implicitly.

### D5. Production guest policy

Use the owner's repeated explicit account-first requirement: unauthenticated visitors may select and prepare a recording locally, but server storage and paid analysis require sign-in, account verification, required profile fields and recording consent. Preserve the selected file through that journey. Historical guest-owned calls remain readable/recoverable only through existing ownership checks. Guest-only code must not reopen unauthenticated production ingestion accidentally.

### D6. Upload capacity

Make capacity and queue timeout explicit configuration. Retain the current production capacity until measured synthetic load proves the next setting safe. First test two simultaneous uploads at supported maximum size/duration, including interruption and disk-pressure cases. Promote capacity to two only if scratch space admission, native helper limits, memory, CPU and request deadlines remain safe. Then evaluate four independently.

Waiting for a slot must produce a truthful queued state, bounded wait/backoff and a machine reason code/Retry-After. Keep the selected local file. Do not report an upload as saved before the server confirms it, and do not repeatedly retransmit a request whose commit outcome is unresolved.

## Corrections to the proposed fixes

1. B1 is not proven to be "mostly wiring" until task, job, reservation, checkpoint and plan state transitions are traced together. Clearing one job marker cannot authorize redispatch against a previously used reservation.
2. B2's retry needs a new immutable attempt/checkpoint lineage and owner-confirmed plan. A fresh button must not reuse a failed cache entry or rerun an uncertain one.
3. B3 must not mint no-charge receipts from any HTTP status or relabel estimated usage as actual invoice cost.
4. B5 must not remove inconvenient evidence checks to manufacture a successful report. If invalid findings are omitted, retain diagnostics, preserve valid source links and coherent indices, and reject when the required report contract is no longer satisfied. No official autonomous numeric scoring is introduced.
5. R9 streaming changes must preserve ownership, deletion serialization and object-integrity fences. A performance cache cannot become an authorization cache or trust only mutable file metadata.
6. U3 should suspend repetitive polling while hidden and resume on visibility/online, with terminal authorization handling. "Never stop" means recovery from transient connection loss, not unbounded requests after deletion or access denial.

## Complete regression queue

`Reported` means the handoff supplied a specific claim; integrated-source reproduction is still required. `Preserve` means a fix exists on an input branch and must pass after merging. No row means deployed.

| ID | Work | State / owning slice |
| --- | --- | --- |
| B1 | Typed provider failure and safe bounded attempt retry | PR1-A observations committed at `ae06445c`, 89 offline tests; durable retry coordinator remains PR1-B |
| B2 | Fresh accepted plan supersedes a recoverable failed attempt | Reproduced by source review at `4bbc`; PR-1; protect uncertain outcomes |
| B3 | Auditable settlement, no-charge evidence and dry-run reconciliation | Paid-stage unsettled holds confirmed by source review; PR-2; D1 governs |
| B4 | Honor approved output limits and bounded truncation repair | Hidden clamps removed in isolated PR3 stack ending `d946d873`; higher-output repair permission remains separate |
| B5 | Admission vocabulary, schema bounds and evidence-safe adaptation | Conservative exact-label correction in isolated `d946d873`; 200 focused tests; schema/local bound mismatch still open |
| B6 | Accepted authority compatibility and execution deadlines | Reported; PR-4; D4 governs |
| B7 | Stage heartbeat, stale-task projection and reconciliation | Reported; PR-4; no unknown replay |
| B8 | Bounded worker/chunk concurrency | Reported; PR-8; benchmark first |
| U1 | Pending upload distinct from confirmed saved submission | Reported; PR-5; include A4 |
| U2 | Stable upload reasons and client duration preflight | Reported; PR-5 |
| U3 | Backoff plus online/visibility recovery | Reported; PR-5 |
| U4 | Auto-start survives status-effect updates | Reported; PR-5; prove idempotent acceptance |
| U5 | Visible reason and one useful recovery action | Reported; PR-1 copy, PR-5 integration |
| U6 | Explicit profile/account execution hold | Reported; PR-4 server, PR-5 client |
| U7 | Capacity queue and truthful busy state | Reported; PR-5 client, PR-8 server |
| U8 | Known states and account-first guest policy | Reported; PR-5; D5 governs |
| R1 | Resume full playback beyond excerpt end | Preserve `2217d41d` / `0d7c15b3` behavior |
| R2 | Working reading-view report navigation | Preserve `f113478f` / `0d7c15b3` behavior |
| R3 | Single summary owner and consistent moment counts | Recheck integrated code; PR-6 |
| R4 | Audio controls remain accessible during review | Recheck integrated code; PR-6 |
| R5 | Useful short-window waveforms on long recordings | Reported; PR-6 plus source-signal contract |
| R6 | Bounded waveform playback rendering | Reported; PR-6 performance evidence |
| R7 | Visible fallback timeline and seek thumb | Reported; PR-6 |
| R8 | Remove empty mobile Playback action | Recheck integrated code; PR-6 |
| R9 | Release DB connection and efficient integrity-safe ranges | Reported; PR-8 |
| R10 | Sheet history and consistent timestamps | Reported; PR-6 |
| A1 | Return from in-page authentication without reload | Recheck merged auth; PR-7 |
| A2 | Allowlisted return path survives sign-in | Reported; PR-7; negative redirect tests |
| A3 | Visible per-address OTP cooldown | Recheck merged auth; PR-7 |
| A4 | Session expiry retains selected file, no phantom call | Reported; PR-5 with U1 and PR-7 |
| A5 | Honest challenge lockout and password fallback | Recheck merged auth; PR-7; non-enumeration preserved |
| A6 | Bounded session preloader with recovery | Reported; PR-7 |
| A7 | Google popup-close/same-tab/slow-return recovery | Recheck signed-receipt merge; PR-7 |
| A8 | Learner workspace routing and shared profile | Recheck merged profile; PR-7 |
| A9 | Library session expiry, return location and scroll | Reported; PR-7 |

## Execution order and acceptance

1. Complete and review the isolated integration merge. Run the entire Sales Xray web suite plus relevant Python suites, then exact-head canonical CI. Keep required compiled browser proof running, not skipped.
2. Land the independently developed named Dipak testing capability only after reviewing owner binding and shared-source isolation. Preserve its separate unit/PostgreSQL evidence. Staging's missing account tester entry and production's existing entry are distinct from provider count caps.
3. PR-1 safe attempt recovery and actionable holds; PR-2 reconciliation; PR-3 admission/token limits; PR-4 authority/deadlines; PR-5 upload/status; PR-6 report/player; PR-7 auth/library; PR-8 infrastructure. Components may be prepared in parallel only with explicit disjoint ownership; integration and activation remain serial.
4. Use synthetic brokers and real disposable PostgreSQL schemas for retry, reservation, ledger and concurrency fault tests. First prove failure scenarios without external provider spend.
5. Staging acceptance must include upload, account completion, report, reload, citation playback, full playback after an excerpt, library reopen, network loss, interrupted upload, same-source repeat, wrong owner, expired grant, budget exhaustion and dispatch ambiguity. Compare standalone web/API versions explicitly.
6. Run the 20-consecutive-attempt reliability target primarily with deterministic synthetic provider fixtures. A separate small approved paid canary is still necessary to establish live-provider behavior. Report sample size, elapsed time, retries and actual/estimated cost separately; do not pass off 20 fixture runs as 20 real-provider calls.
7. Promote only the exact tested release with its authorized policy delta, existing budgets and rollback reference. Verify production after deployment. No completion claim solely from a green merge or a completed cloud research answer.

## Current communication

### Bounded source review: accepted refinements

The existing Pro architecture task and an independent Luna source review both confirm that the queue retry flag alone is not a complete B1/B2 repair. Pin: `4bbc2b790431949314d5464fe1973b62d02f87e7`. This is design review, not execution or production proof.

- Keep failure evidence separate from `Job.provider_receipt`: existing receipt consumers use that field as evidence of successful completion. A typed failure placed there could falsely acknowledge a job.
- An eligible retry needs a new quote, reservation, run, task and job, plus append-only root/predecessor/ordinal/accepted-plan/evidence linkage. `Checkpoint.replicate` can distinguish execution identity, but must also be reconstructed consistently by planner, worker and checkpoint validation.
- Bind observations to the exact provider attempt and input. The broker reports sanitized bounded observations; the parent derives permissions. Missing or invalid observations remain unknown. Persist failure evidence before admitting a successor.
- Preserve the initial commitment when billing is uncertain and reserve the entire successor cost separately. The current `NoChargeReceipt` requires no execution as well as no charge; a documented token-free provider error alone does not satisfy it.
- Share a single explicitly accepted additional C5 attempt across structural, transient and output-limit repair unless the accepted contract expressly provides separate finite pools. A new plan ID cannot reset lineage counts. Historical plans gain no new retry permission implicitly.
- Preserve returned output under dispatch-time evidence; re-check current compatible permission for any subsequent dispatch. Revocation and retention remain enforced.
- Dipak's explicit `provider_stage_request_count` exemption applies only to ordinary base stage request counts for his currently verified canonical account. It does not waive supplement/repair attempt limits, unknown-outcome holds, project budgets, privacy or identity checks. A separately authorized owned recording is distinct from replay of an unknown attempt on the same logical recording.

Independent B4/B5 probes used only synthetic fixtures and passed the existing 142-test focused suite at `4bbc`. They do not prove a production provider emitted those malformed shapes. Repeat the probes on the integrated head before editing. Keep local schemas and evidence checks strict; confirm provider-supported schema keywords before changing the wire contract.

The probes were repeated on integration base `7ff3581f`. The isolated PR3 stack now ends at `d946d873b8e64f6e50ddef55a81a61882058db61`, with 200 focused tests passing. Two intermediate token-matching approaches failed independent review because they newly admitted score-like field names. The final implementation preserves the original denial rule for unknown names and exempts only reviewed exact language labels. Intermediate commits are not independently approved for release. No findings were discarded, schemas relaxed, repair permission increased or provider called.

PR1-A at `ae06445c4151dc1e842441ca1d832de1330ef8f9` now transports bounded, input/attempt/quote-bound failure observations. It hashes provider request identifiers and carries no remote error text. Its 89 passing tests establish transport behavior only; it does not enable retry, settle charges or alter job/ledger state.

The named tester scope at `dd65cbe913e761e4a97b86193a8a2c82e86f4c12` passes initial scope and PostgreSQL admission checks but is held for a concurrency correction. Independent review found a new human-identity lock taken after the budget lock, opposite authenticated account ordering. The fix must follow the existing processing-owner read contract in `guest_ownership.py`, retain current verification checks, and pass a deterministic database concurrency regression plus second-recording report completion before release.

The WhatsApp message for Dipak is a draft only. Do not say "fixed" or "unlimited on both environments" until both the named account settings and same-source analysis journey are verified. The current diagnosis supports an exhausted source-scoped report-attempt allowance, while the displayed request reference has not been linked to a precise stage event. Production's existing unlimited account setting alone does not solve it.
