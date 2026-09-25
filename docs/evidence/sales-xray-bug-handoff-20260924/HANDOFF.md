# Sales Xray — frustration-bug handoff for the main Codex coding agent

- **Date:** 24 September 2026
- **Prepared by:** Claude Code (read-only investigation; no product code was changed, nothing was committed, deployed or sent to a provider)
- **Requested by:** Suyash (founder)
- **Audience:** the main Codex coding agent that owns Sales Xray integration and release
- **Goal:** make Sales Xray stop feeling broken. A user should upload once, see truthful progress, get a report, and be able to listen to it without fighting the UI.

> Read §0–§3 before touching code. §0 contains a stack-integration hazard that will otherwise cause you to re-fix bugs that are already fixed on another branch, or to lose those fixes.

---

## Contents

- §0 Source pin, branch topology and an integration hazard (read first)
- §1 Non-negotiable constraints for every fix
- §2 Already fixed, do not redo
- §3 Priority order and suggested PR slicing
- §4 Backend pipeline bugs (B1–B8): calls that never become reports
- §5 Upload and progress bugs (U1–U8)
- §6 Report and playback bugs (R1–R10)
- §7 Sign-in, account and library bugs (A1–A9)
- §8 Live production observations (guest surface only)
- §9 Verification plan and definition of done
- §10 Questions that need the founder or controlled documents
- Appendix A: file index
- Appendix B: test commands

### Evidence legend

| Mark | Meaning |
|---|---|
| ✅ **Verified** | The cited lines were read directly at the source pin during this investigation, and the code does what is described. |
| 🔎 **Traced** | Found by a sub-agent tracing the code path end to end at the source pin. Plausible and specific, but re-read the lines before editing. |
| ⚠️ **Branch-dependent** | The state differs between the #67 stack tip and `codex/sales-xray-v02-intake`. See §0. |

All line numbers are at **`4bbc2b79`** (`codex/sales-xray-s1-processing-diagnostics`) unless marked `v02@…`. Paths are relative to the repo root.

---

## §0 Source pin, branch topology and an integration hazard (read first)

### Repo and checkouts

- Repo: `github.com/authorityclosers/authority-closers-platform`
- Primary local checkout: `D:\Projects\authority-closers-platform`. Its local `main` is **stale** (`65b1f36c`, 11 Sep). Do not build from it.
- `origin/main` = `e087d481` (19 Sep).
- There are **253 git worktrees** of this repo, under `D:\Projects\authority-closers-*`, `D:\AC-authority-closers-release-audit\*` and `C:\Users\Suyash\.codex\worktrees\*`. Do not delete any of them. Some hold untracked operational files.
- The investigated checkout was `C:\Users\Suyash\.codex\worktrees\sales-xray-s1-processing-diagnostics\authority-closers-platform` @ `4bbc2b79`.

### Open PR stack (all into one chain)

```
main (e087d481)
 └─ #63 codex/sales-xray-reliable-20260922      "Recover Sales Xray reports and support bounded 60-minute calls"  (runtime 270a4b57 is DEPLOYED TO PRODUCTION per PR body)
     └─ #64 codex/sales-xray-v02-intake          "Sales Xray v0.2: versioned coaching, report language and confirmed progress"
         └─ #65 codex/hosted-stage-source-supplement-20260923  "Bound staging coaching retries and retain report moment evidence"
             └─ #66 codex/sales-xray-account-edge "Release Sales Xray account recovery and continuous coaching reports"
                 └─ #67 codex/sales-xray-s1-processing-diagnostics "Preserve bounded diagnostics for held processing plans"   ← TIP, 4bbc2b79
```

`codex/sales-xray-auth-release`, `codex/sales-xray-account-edge` and `codex/sales-xray-auth-mobile-fit-20260924` are fully contained in the tip.

### ⚠️ Hazard: `codex/sales-xray-v02-intake` has moved ahead of the stack

`#65` was stacked on an **earlier** v02-intake. Since then, v02-intake has gained commits that are **not in the tip**. `git cherry` shows **9 commits that are not patch-equivalent**, because several are parallel versions of the same work done on `account-edge`:

| Commit | Subject | Relevance |
|---|---|---|
| `2217d41d` | fix(sales-xray): let playback escape excerpt bounds | **Fixes R1** (see §6) |
| `0d7c15b3` | fix(sales-xray): preserve report navigation and clip bounds | Related to R1 and R2 |
| `f113478f` | fix(sales-xray): polish report reading and playback | Report CSS and behaviour; overlaps R3, R4 and R8 files |
| `5bed4852` | fix(sales-xray): prevent paused processing overlap | Paused-panel layout (U5 area) |
| `e57c1084` | Add continuous Sales Xray report reading view | Parallel implementation of #66's "continuous reading" |
| `4f1d7a04` | Bind Google account completion to signed flow receipt | Parallel to `0e0eca6e` on `codex/sales-xray-auth-recovery` |
| `f84dbe0c` | Fit profile entry and simplify phone and password input | A8 area |
| `7532a82a` | Highlight selected recording on account access | Auth UI |
| `e03794be` | Clarify email-code outage and surface password fallback | A3 and A5 area |

Two more branches have commits outside the tip:
- `codex/sales-xray-avatar-transport-20260924`: 1 commit (`b6f1cf70`)
- `codex/sales-xray-auth-recovery`: 2 commits (`0e0eca6e`, `1c9f905a`)

Verified on `v02-intake` head (⚠️):
- **R1 fixed there.** The dock's Play button now calls `onPlay?.()`, wired to `setMoment(null)` (`v02@acquisition-studio.tsx:2641`, `v02@call-audio-dock.tsx:55`). The tip does **not** have this.
- **R2 fixed there.** `focusInsight` calls `navigateToReport("overview", number)` when `!showHeading` (`v02@dipak-overview.tsx`). The tip returns early and does nothing.
- **Still present there:**
  - R3: `data-compact={!showHeading && !reading}`
  - R4: `showModal`
  - R6: a `timeupdate` state update per provider
  - R8: `audioPlayer` is null when `reportReady`, but the Playback toggle still renders
  - A1: `href="/"`
  - A2: `location.assign("/")`
  - A3: silent `retryAt` return
  - U1: `rememberSubmission(id)` before the PUT
  - U3: stop after 3 failures
  - U5: `pausedFailureMessage` returns `""`

**Required first step:** decide the integration base. Recommended:
1. Create one integration branch from `4bbc2b79`.
2. Merge (not rebase) `codex/sales-xray-v02-intake`, `codex/sales-xray-auth-recovery` and `codex/sales-xray-avatar-transport-20260924` into it.
3. Resolve conflicts in `acquisition-studio.tsx`, `dipak-overview.tsx`, `report-modes.tsx`, `account-auth.tsx` and `auth/complete/*`, preferring the behaviour that satisfies both branches' tests.
4. Run the full web and Python test suites.
5. Only then start on the bugs below, re-checking every ⚠️ item.

Keep one owner for deployments, as recommended by `docs/evidence/sales-xray-audit-20260922/RECOVERY_PLAN.md` §1.

### Deployment state (from PR #63 and the 22 Sep audit)

- **Production** runtime `270a4b57` (from #63) is an ancestor of the tip. The production standalone web SHA may differ from the API SHA; confirm.
- **Staging** was at `dd6ee881` on 22 Sep and may have moved since. Confirm before any live verification.
- On 22 Sep, staging's latest recording `17297ffe-d78e-46ca-94bf-b155cab0834a` was held at C5 with `conversation_report_overview_invalid`. There were 11 held plans in 5 days and zero report drafts. The fixes in #63 onward address the specific validator defects, but B1, B2 and B5 below are why calls still end up held.

---

## §1 Non-negotiable constraints for every fix

These come from `AGENTS.md` and the existing design of this codebase. Violating them turns a UX fix into a money or audit bug.

1. **No double provider spend.** Never re-dispatch a provider call whose outcome is *unknown*: a timeout after sending, a crash after the dispatch marker, or a lost response. Re-dispatch only when the provider **explicitly returned** a failure, or when the request provably never left the box.
2. **Supersede, never overwrite.** Keep old tasks, receipts, reservations, raw responses and negative validations. New attempts are new rows or versions. (`AGENTS.md`: "Do not overwrite audit-critical history; supersede.")
3. **No direct SQL recovery.** Recovery goes through the Admin or CLI services (`retained_c5_recovery_cli`, etc.).
4. **No secrets or provider bodies in logs, errors or diagnostics.** Keep using the content-free code vocabulary (`provider_failure_code`, `InferenceBrokerError` stable codes).
5. **Do not infer protected business semantics.** Anything that changes *who pays*, *what counts against a budget* or *what users are allowed to do* needs founder or controlled-document confirmation. These are flagged in §10. Where unsure, implement the mechanism behind a setting defaulted to current behaviour, and ask.
6. **Every change needs tests.** For ledger, reservation or plan-state changes, that means **real PostgreSQL** tests (the repo already has disposable-schema patterns), not only mocks.
7. **No numeric scoring.** Do not introduce official scores while touching report validation (`AGENTS.md`, AC-SVAL gates). Relaxing the numeric-*key* check (B5) must still reject numeric scoring *values*.
8. **Bump `REPORT_VALIDATOR_REVISION`** (`reports.py:1524`, currently `ac.sales-xray.report-validator/2`) whenever report admission or adaptation semantics change. Otherwise retained recovery will replay old negative results. Add a guard test (see B5).

---

## §2 Already fixed, do not redo

The 22 Sep audit (`docs/evidence/sales-xray-audit-20260922/`, untracked in `D:\Projects\authority-closers-platform`) reproduced three defects. **All three are fixed at `4bbc2b79`.** Verified by source reading and by re-running probes.

| Audit defect | Status | Where |
|---|---|---|
| Improvement and missed-opportunity details joined by array position, so wrong evidence was attached | **FIXED** | `reports.py:1548-1561` (`indexed_details` by explicit `finding_index`, rejects duplicates and out-of-range), used at 1584 and 1604. Frontend also joins by `finding_index` (`dipak-overview.tsx:864-872, 902-904, 1029-1031`; `overview-dashboard.tsx:42-44`; `overview-contract.ts:250-265`). |
| Flattened overview + scalar improvement rejected as `report_overview_invalid` | **FIXED** | Flattened normalization at `reports.py:2160-2187` now runs before scalar adaptation at 2190. All five audit shapes are accepted. |
| Recovery fingerprint lacked a validator revision, so a parser upgrade could not supersede `needs_correction` | **FIXED** | `retained_c5_recovery.py:926-928` includes `REPORT_VALIDATOR_REVISION`. |

Notes:
- The audit's own probe script (`audit-probes.py`) still "reproduces" defect 3, because its mocked DB returns the old row for any query. **That probe is no longer a valid regression check.** Replace it with a real PostgreSQL test if you want a guard.
- Residual risk: `REPORT_VALIDATOR_REVISION` is a manual constant. Validator code changed in about 8 commits since `/2` without a bump. See the B5 guard test.
- The Gemini response schema is only **partly** adopted: `responseJsonSchema` is sent only for structured coaching (`gemini_tasks.py:61-72`). C4 fact extraction on every route, and C5 on non-structured routes, still use bare JSON mode. See B5.

---

## §3 Priority order and suggested PR slicing

Ordered by how much real users feel it. Do §0 integration first.

| PR | Scope | Bugs | Why first |
|---|---|---|---|
| **PR-1** | Retryable provider failures and a real retry path for held plans | B1, B2, U5 (copy + action) | Today one 429 kills a paid call forever, and "Request a fresh plan" cannot revive it. This is the #1 reason calls end as "Analysis paused". |
| **PR-2** | Budget settlement and no-charge release | B3 | Silent time bomb: the shared provider budget drains at worst-case price until *every* new call is refused. |
| **PR-3** | Report admission robustness | B4, B5 | Long calls truncate; near-valid AI output is rejected with zero repairs. |
| **PR-4** | Plan authority, deadlines and stuck-task sweeper | B6, B7, U6 | In-flight analyses killed by config edits, the 1-hour window and crashed workers. |
| **PR-5** | Upload and progress frontend, plus stable server reason codes | U1, U2, U3, U4, U7, U8 | The phantom saved call, dead polling, lost auto-start and misleading upload errors. |
| **PR-6** | Report and player | R1–R10 (after §0 merge; R1 and R2 may already be done) | The main listening experience. |
| **PR-7** | Sign-in and library | A1–A9 | Sign-in dead ends and lost context. |
| **PR-8** | Streaming and infra | R9, U7 (server side), B8 | Scalability; the one-upload-at-a-time and DB-connection-held-during-streaming problems. |

PR-1 and PR-5 have the highest "feel" payoff. PR-2 prevents an outage.

---

## §4 Backend pipeline bugs (B1–B8): calls that never become reports

Stage vocabulary: C0/C1 = intake and measurement, **C2 = transcription**, C3 = alignment, **C4 = fact extraction**, **C5 = coaching report (Gemini/Groq)**, C6 = final.

### B1 — P0 — One temporary provider error permanently kills the stage ✅

**User experience:** the call uploads, and transcription or analysis starts. Then Gemini, Groq, Deepgram or ElevenLabs returns one 429, 500, 502, 503 or 504, and the call becomes "Analysis paused" forever. The user is told to ask the AC team. Nothing retries automatically.

**Where:**
- `packages/python/ac_platform/conversation_intelligence/inference_worker.py:577` records `dispatch_started_at` **before** the provider call at `:617` (`await self.broker.execute(...)`).
- `inference_worker.py:829-835`: *every* exception goes to `self._fail(work, failure_code=provider_failure_code(error))`.
- `inference_worker.py:717-778` (`_fail`):

```python
ambiguous = job.dispatch_started_at is not None          # :729, true for ANY failure after the marker
...
task.state = "uncertain" if ambiguous else "failed"      # :743
...
if ambiguous and existing.state == "in_flight":
    transition = mark_uncertain(...)                     # :756-763, reservation held at full max cost
...
await JobRepository(db).fail(job, work.lease_token, failure_code,
                             permanent=True,             # :776, ALWAYS permanent
                             ambiguous=ambiguous)
```

- `outbox/repository.py:2071`: `dead_letter = permanent or row.attempt_count >= row.max_attempts`, so `max_attempts=3` (`inference.py:597`) is never used.
- `processing_plan.py:1221-1226`: any task in `failed`, `uncertain` or `cancelled` puts the plan in `held` with `failure_code = "stage_<state>"`.

**Root cause:** the worker treats "the provider explicitly answered with a non-200" the same as "we don't know what happened". The provider HTTP layer already produces a precise code:
- `providers.py:125-126`: `if response.status_code != 200: failure = ProviderError(f"provider_http_{response.status_code}")`
- `inference_broker.py:56`: `_PROVIDER_HTTP_ERROR = re.compile(r"^provider_http_[1-5][0-9]{2}$")`, which is allowed as a stable code at `:231`
- `provider_failure_code` maps it to `conversation_provider_http_<status>` (`inference_worker.py:214-219`)

**The job queue already supports the correct behaviour** (`outbox/repository.py:700-707`):

```python
if not dead_letter and not ambiguous:
    # A provider returned an explicit retryable failure, so no external
    # effect is unresolved. Reset this attempt's pre-effect marker before
    # scheduling the automatic retry; crash-ambiguous paths never do this.
    values["provider_idempotency_key"] = None
    values["dispatch_started_at"] = None
```

The conversation inference worker never calls it that way.

**Fix direction:**
1. In `_fail`, or in a classifier it calls, split failures into three classes:
   - **(a) Explicit provider-returned, retryable:** `provider_http_429`, `provider_http_500`, `_502`, `_503`, `_504`, and possibly `_408`/`_529` (confirm per provider). The HTTP response came back, so the request is finished.
   - **(b) Explicit provider-returned, not retryable:** other `provider_http_4xx` (400, 401, 403, 404, 413, 422), `provider_audio_or_model_invalid`, `provider_model_not_supported`, `provider_prompt_too_large`, `provider_payload_invalid`. Also finished, but retrying won't help.
   - **(c) Unknown outcome:** `broker_timeout`, `provider_execution_deadline`, `provider_transport_or_response_failed`, `TimeoutError` from `asyncio.timeout(_EFFECT_SECONDS)`, process death, `broker_process_*`, and anything else. **Keep the current behaviour** (uncertain, reservation held), but see B7 for the reconciliation path.
   - Pre-dispatch broker failures that never reached the network, if distinguishable (e.g. `broker_request_invalid`, `broker_reservation_invalid`, `provider_dispatch_not_authorized`), belong to "not dispatched" and must release as today. Confirm each code's position relative to the actual network send in the broker child before classifying it.
2. For **(a)**:
   - Release the attempt's reservation with a typed `NoChargeReceipt` (`entitlements.release(..., no_charge_receipt=...)`, `entitlements.py:716-740`). Bind the receipt to the reservation and attempt, with an evidence ref like `provider-returned-http-<status>:<run_id>`.
   - Set the task back to a retryable state (e.g. `queued`/`pending`, whatever the task state machine allows), **not** `uncertain`.
   - Call `JobRepository.fail(..., permanent=False, ambiguous=False)` so the queue clears the marker and schedules backoff (`retry_policy.delay_for_attempt`).
   - Bound this by `max_attempts`.
   - Honour `Retry-After` if you capture it. The body is intentionally discarded at `providers.py:127-140`; headers could be captured as a bounded integer without breaching the no-free-text rule.
   - **Ledger constraint:** `mark_dispatched` (`entitlements.py:665-668`) refuses a second attempt on the same reservation: `"reservation cannot dispatch a second provider attempt"`. So each retry needs either (i) a **new reservation** under the same accepted quote and plan allowance, or (ii) a new explicit transition `in_flight → reserved` that requires a `NoChargeReceipt`. Option (i) fits "supersede, never overwrite" best. Ensure per-source allowance and plan maximum-cost accounting do not double-count the released attempt.
3. For **(b)**: release with a no-charge receipt and mark the task `failed` (not `uncertain`) with the precise code, so B2's retry path can run once an operator fixes credentials or configuration.
4. Keep `provider_failure_code` output content-free. Add the classification as a pure function with a table-driven unit test.

**Tests to add:**
- Unit: classifier table for every stable code in `inference_broker._STABLE_ERROR_CODES` plus `provider_http_1xx–5xx` samples.
- PostgreSQL:
  - A synthetic broker returns `provider_http_429` on attempt 1 and success on attempt 2. Assert: exactly two broker calls; the first reservation is released with a no-charge receipt; the second is settled or reconciled; the task is `completed`; the plan is not held; the budget is not double-counted.
  - A synthetic broker returns 503 three times. Assert: dead-letter after `max_attempts`; the task is `failed` (not `uncertain`); every reservation is released with no-charge receipts; the plan is held with `conversation_provider_http_503`.
  - A timeout after dispatch (class c). Assert: the behaviour is unchanged from today (uncertain, reservation held, no second dispatch).
  - Concurrency: two workers cannot both claim the retry.

**Acceptance:** with a provider that fails transiently once, a real upload completes without human action, and the ledger shows one no-charge release and one settled or reconciled attempt.

---

### B2 — P0 — A held plan can never recover; "Request a fresh plan" pauses again at once ✅

**User experience:** after any held stage, the UI offers "Request a fresh plan" or "Review and continue analysis" (`acquisition-studio.tsx:1083-1096` `freshPlan()`, buttons at `:1745`, `:2398`, `:2463`, `:2476`). The user approves a new plan and it is immediately held again. The only ways out are an admin changing prompt, model or token settings (which changes the cache key), or re-uploading the audio (which only reuses the transcript).

**Where:** `processing_plan.py:996-1017` (`_enqueue`):

```python
existing = await self.db.scalar(
    select(ConversationInferenceTask).where(
        ConversationInferenceTask.recording_id == row.recording_id,
        ConversationInferenceTask.cache_key == stage.checkpoint.cache_key,
    )
)
if existing is not None:
    ...
    if existing.state == "completed":
        ...
    return existing        # :1017, returns failed/uncertain tasks too; the coordinator then re-holds (:1221-1226)
```

- There is one task per `(recording_id, cache_key)` (`models.py:391`, unique constraint).
- The cache key has no plan or attempt identity: `checkpoints.py:104-117`, with the docstring *"changed outputs need an explicit new replicate."* The `replicate` field exists for exactly this purpose, but **no caller ever sets it**.
- No code transitions a plan from `held` back to `active`.

**Fix direction:**
1. When the coordinator or `_enqueue` finds an existing task for the cache key in state:
   - `failed` with a class-(a) or class-(b) code from B1 (i.e. provably no unresolved provider effect), **or**
   - `uncertain` that has since been **reconciled** as no-charge through the supported Admin/CLI path (B7),
   
   then, **for a newly accepted plan only**, build the stage checkpoint plan with `replicate = f"retry:{plan_id}"` (or an attempt ordinal bound to the plan). That yields a new cache key and a new task row. Keep the old row untouched.
2. **Never** create a replicate while an older task for the same stage is `uncertain` and unreconciled, because that risks double spend. Instead, surface a specific hold reason, e.g. `stage_outcome_unknown_pending_reconciliation`, which the UI explains (U5).
3. Allow a new accepted plan to supersede a held plan: the old plan stays `held` for history, and the new plan becomes `active`. Check how `acceptance_intent` and `command` identity (`processing_plan.py:386-390`) should bind to the new plan.
4. Respect per-source allowance, max-repair and budget rules. A retry must be quoted and accepted like any other plan (`AGENTS.md` #5; see §10 Q2 on whether retries of provider-failed attempts should count against the user's allowance).

**Tests (PostgreSQL):**
- A held plan with a C5 task `failed` from `provider_http_503`: accept a fresh plan and assert a new task with a different cache key, the old task unchanged, and the plan completes.
- A held plan with a C5 task `uncertain` and unreconciled: a fresh plan is refused or held with the specific reason, and zero broker calls happen.
- Completed C2 and C4 checkpoints are reused by the fresh plan, with no re-transcription.

**Acceptance:** a user whose call paused because of a provider error can click one button and get a report, without re-uploading and without admin help.

---

### B3 — P0 (budget outage) — Reservations are never settled, so the shared provider budget drains at worst-case price ✅/🔎

**User experience:** nothing at first. Then, once enough calls have run (including failed ones), every new call is refused with *"The provider budget cannot cover this complete plan."* (`processing_plan.py:843-844`).

**Where:**
- On success, `inference_worker.py:704-711` calls `mark_uncertain(..., f"provider-cost-reconciliation:{run_id}")`. The receipt says `"cost_state": "reconciliation_required", "actual_cost_paise": None` (`:692-693`).
- On failure after dispatch, `inference_worker.py:756-763` also calls `mark_uncertain`.
- `entitlements.py:352-359`: an `uncertain` reservation counts at **full `quote.max_cost_paise`** (`committed_paise` returns `self.quote.max_cost_paise` unless it is `released`, `settled` or `reconciliation_required` with a settlement).
- `settle()` exists (`entitlements.py:691-713`), but the only callers are `worker.py:914` (C1) and `reporting_pipeline.py:695` (🔎 confirm which ledger that is). Nothing settles C2, C4 or C5 (🔎).

**Fix direction:**
1. **On success:** compute actual cost from `output.usage` (already in the receipt, `:691`) times the approved token or minute rates. There is an existing basis string in `admin_pricing.py:203,222`: `"provider_input_and_output_tokens_x_approved_token_rates"`. Build a typed `SettlementReceipt` and call `settle()`. If usage is missing or unparseable, keep today's `uncertain`, but record why.
2. **On an explicit provider-returned failure (B1 a/b):** `release(..., no_charge_receipt=...)`.
3. **Backfill:** add a supported CLI or Admin action, append-only and idempotent, that walks existing `uncertain` reservations that have a validated provider receipt with usage, and settles them. It must also release reservations whose job failed with `provider_http_*` using a no-charge receipt. **No direct SQL.** Dry-run mode by default, with a report of paise freed.
4. Expose "uncertain paise outstanding" in the Admin provider or budget view, so this can't silently recur.

**Business confirmation needed (§10 Q1):** the exact settlement pricing source (approved rates vs provider invoice), and whether a provider 5xx is treated as no-charge for each provider.

**Tests:** PostgreSQL tests for settle on success; release on explicit failure; idempotent backfill replay; overrun (`actual > max`) goes to `reconciliation_required`, not silently capped.

**Acceptance:** after N synthetic successful calls, `available_paise` decreases by roughly the actual cost, not N × max cost. The backfill frees staging and production budget with an auditable receipt trail.

---

### B4 — P1 — Long calls get truncated (MAX_TOKENS); Admin token settings are silently ignored ✅

**User experience:** long or dense calls (the product advertises 60 minutes) pause at C4 or C5. Staging already hit MAX_TOKENS at C4 with 1,400 tokens, and at C5 with 3,196 of 3,200.

**Where:** `report_overview.py:21-31`:

```python
def stage_completion_limit(stage, approved_maximum, *, provider="", model=""):
    ...
    if approved_maximum > 4_000:
        return approved_maximum
    return min(3_200 if stage == "C5" else 1_400, approved_maximum)
```

- Admin allows up to 4,000 (`analysis_settings.py:28,66`, 🔎), so any Admin value from 1,401 to 4,000 for C4 is silently clamped to **1,400**. That count includes Gemini "thinking" tokens (`thinkingConfig: LOW`, `gemini_tasks.py:59`).
- A truncated response fails with `gemini_response_incomplete` (`gemini_tasks.py:313-314`, `finishReason != "STOP"`).
- That code is in `_VALIDATION_FAILURES` but **not** in `C5_REPAIR_FAILURE_CODES` (`contracts.py:61-75`), so there is no repair.

**Fix direction:**
1. Make `stage_completion_limit` return the approved maximum, bounded only by `completion_ceiling(provider, model, stage)`. Remove the hidden 1,400 and 3,200 clamps, or move them into a documented default that the Admin value overrides.
2. Ensure quotes and `max_cost_paise` reflect the larger limit, so budget admission stays truthful.
3. Make `gemini_response_incomplete` with `finishReason == "MAX_TOKENS"` eligible for **one** bounded repair at a higher limit, within the already-approved plan budget (confirm under §10 Q3). Alternatively, chunk C4 smaller: C4 already chunks (`processing_plan.py:1145-1152`), so reduce chunk size when the call is long.
4. Consider `thinkingLevel` or `thinkingBudget` so thinking cannot eat the output budget.

**Tests:** a unit test that `stage_completion_limit("C4", 3000, ...) == 3000`; a quote-cost test at the higher limit; a PostgreSQL repair test where MAX_TOKENS on attempt 1 is followed by a success on the repair at a higher limit.

---

### B5 — P1 — Near-valid AI output is rejected outright, usually with no repair and no reason ✅

**User experience:** analysis runs, the provider returns a mostly good report, and the call pauses with no explanation.

**Concrete causes:**

1. **The numeric-key check matches substrings** (`reports.py:167-170` and `:877-881`):

   ```python
   _FORBIDDEN_NUMERIC_KEY = re.compile(
       r"(?:score|grade|rating|points?|numeric|percent|percentage|rank|overall_score)",
       re.IGNORECASE,
   )
   ...
   if isinstance(key, str) and _FORBIDDEN_NUMERIC_KEY.search(key):
       raise ReportError("report_numeric_field_forbidden")
   ```

   Keys such as `pain_points`, `key_talking_points`, `turning_point`, `talking_points`, `upgrade`, `ranking_context` and `prank` all fail. This is very likely with sales-coaching output ("pain points", "talking points").
   - **Fix:** match on whole tokens split by `_`/camelCase, e.g. tokens ∈ {score, scores, grade, rating, ratings, numeric, percent, percentage, rank, overall_score}. Decide whether `points` alone should be forbidden only as an exact key.
   - Better still, reject **numeric scoring values** (int/float in fields that look like scores) rather than key names.
   - Keep AC-SVAL intent: no scores (§1.7).

2. **One finding with empty evidence rejects the whole report** (`reports.py:1509-1511`): `if not isinstance(evidence, list) or not evidence: raise ReportError("report_finding_evidence_missing")`.
   - **Fix:** drop that single finding and record a bounded diagnostic, provided at least the required minimum of valid findings remains. Keep strict source/quote validation for everything retained.
   - If dropping breaks index coherence (`finding_index`, `improvement_index == 0`, `next_call_focus`), re-index the same way `reports.py:1616-1678` already does for details.

3. **Unrecognised validation codes collapse to a non-repairable generic code.**
   - `inference_worker.py:187-209` `_VALIDATION_FAILURES` lists 19 codes. Any other `InferenceTaskError` code becomes `conversation_provider_result_validation_failed` (`:225`), which is **not** in `C5_REPAIR_FAILURE_CODES` and is dropped by the progress API (`acquisition_reports.py:98-115`, 🔎).
   - 🔎 About 40 `ReportError` codes raised in `reports.py`/`report_overview.py` are missing, including `report_numeric_field_forbidden`, `report_finding_evidence_missing` and `overview_focus_required`.
   - **Fix:** define the validation-code vocabulary once (an enum or frozenset in `contracts.py`). Derive `_VALIDATION_FAILURES` and `C5_REPAIR_FAILURE_CODES` from it, and decide explicitly which are repair-eligible.
   - **Guard test:** statically collect every `ReportError("...")`/`InferenceTaskError("...")` literal in `reports.py`, `report_overview.py` and `report_structure.py`, and assert each is in the vocabulary.

4. **The schema sent to Gemini has no size bounds, but the parser has hard ones** (🔎).
   - The parser allows at most 3 strengths, improvements and details, and requires `improvement_index == 0`. The schema has no `maxItems`/`maxLength`/`minimum`/`maximum`, so four strengths → `report_overview_invalid` (confirmed by probe), with only one repair.
   - **Fix:** add the same bounds to the JSON schema (`coaching_generation_json_schema`). Or deterministically keep the first N valid items and record a diagnostic, rather than failing.

5. **The scalar adapter can invalidate its own output** (🔎). If the first improvement is dropped, `next_call_focus` is nulled and the report then fails `overview_focus_required`. **Fix:** re-point focus to the new first improvement, or drop focus only if the contract allows it to be optional.

6. **Bare JSON mode without a schema for C4 and some C5 routes** (`gemini_tasks.py:55-73`; the schema is only added when `structured_coaching`).
   - **Fix:** add a response schema for C4 fact packets and remaining C5 routes where the model supports it. Validate per model, and update frozen request hashes and plan revisions correctly.
   - This reduces shape drift; it does not replace local source/evidence checks.

**Also:** bump `REPORT_VALIDATOR_REVISION` (§1.8). Add a test that fails if the validator source hash changes without a revision bump (e.g. store the hash of the validator function sources in a fixture that must be updated along with the revision).

**Tests:** a synthetic regression matrix covering the RECOVERY_PLAN §2 list: nested and flattened, structured and scalar, reordered/missing/duplicate indexes, extra keys, `pain_points`-style keys, empty-evidence finding, 4 strengths, dropped first improvement, truncated JSON, MAX_TOKENS. Negative evidence (fabricated or mismatched quotes) **must still reject**.

---

### B6 — P1 — Config changes and the 1-hour plan window kill in-flight analyses and waste paid output ✅/🔎

**User experience:** analysis is running, an operator adds a tester, allowance or stage supplement (or the approval bundle is re-issued, e.g. on deploy), and every in-flight analysis pauses with the generic `processing_authorization_or_input_unavailable`. Slow queues or a user who took a while to approve hit the same wall after one hour.

**Where:**
- `processing_plan.py:378-392`: every scheduler step re-checks, among other things:
  - `not value.created_at_epoch <= int(now.timestamp()) < value.expires_at_epoch` (:384)
  - `bundle.digest != value.authority_sha256` (:385)
  
  and raises `ConversationDenied`.
- The digest includes `deployment_ref` and `issued_at` (`activation_contract.py:542-566`, 🔎), so *any* re-issue changes it.
- `processing_plan.py:1280-1293`: `ConversationError`/`InferenceTaskError` during `advance` puts the plan in `held` with `processing_authorization_or_input_unavailable`. That is the generic message users see.
- 🔎 After the provider returns, the worker re-derives scope (`inference_worker.py:640-648`). If the quote's `authorization_ref` (which embeds the bundle digest, `authority.py:1266,1302`) no longer matches, `_fail` runs **after the provider was paid**, the task goes `uncertain`, and B2 blocks any retry. Confirm this exact path.
- `processing_plan.py:881-886`: `expires_at_epoch = min(now + 3600, bundle.expires_at_epoch, ...)`, counted from **quote** time and never renewed. It is checked at every step.

**Fix direction:**
1. **Never discard a returned, paid provider result because authority changed after dispatch.** Authorization was valid when the marker was written. Validate and save the checkpoint (it is already protected by `already_started_effect`), then let the *next* stage re-check authority.
2. Bind an accepted plan to the **bundle revision it was accepted under**. Allow continuation under a newer bundle if the change is compatible: same provider route and model, caps not lowered, and the user and tester not revoked. Define "compatible" with the founder or controlled docs (§10 Q4). Deny only on true revocation.
3. Separate the **approval window** (time to accept a quote) from the **execution deadline** (time for stages to run). Start the execution deadline at acceptance, and consider per-stage deadlines sized to call duration.
4. Replace the generic hold code with specific ones (`plan_authority_revoked`, `plan_approval_expired`, `plan_execution_deadline`) so the UI can explain and offer the right action (U5).

**Tests (PostgreSQL):** re-issue the bundle mid-C4 with a compatible change and assert the plan completes; revoke the tester mid-plan and assert it is held with the specific code and no provider dispatch; a paid C5 response returned after a bundle re-issue is saved, not lost.

---

### B7 — P1 — A crashed worker, or an uncertain outcome, leaves users watching "processing" with no path out 🔎

**User experience:** "Writing your coaching report…" for up to an hour, then the generic pause.

**Where:**
- On lease loss or crash, only the job row is quarantined (`outbox/repository.py:442-470`); the task stays `running`.
- There is no stage heartbeat or deadline. The plan only fails when the 1-hour expiry (B6) trips.
- Uncertain outcomes have no supported reconciliation action that feeds back into B2.

**Fix direction:**
1. Add a stage deadline and sweeper. When a job is quarantined or dead-lettered after dispatch, move the task to `uncertain` promptly with a specific code, instead of leaving it `running`.
2. Provide an Admin/CLI **reconcile** action for uncertain tasks:
   - "confirmed no charge" → release with a no-charge receipt → B2 retry becomes allowed
   - "confirmed charged, result lost" → settle, then allow a bounded paid retry under approval
   - Append-only, audited.
3. Surface the uncertain state to the user honestly: "We're confirming the outcome with the AI provider. You won't be charged twice." Show a request reference.

---

### B8 — P2 — The worker processes one job at a time; C4 chunks run sequentially 🔎

**Effect:** queue latency adds straight into the B6 one-hour window, and long calls with many C4 chunks are slow.

**Where:** a single worker claim loop (`inference_worker.py:780` `run_once`); C4 chunks are enqueued in order (`processing_plan.py:1145-1152`).

**Fix direction:** allow bounded concurrency (N leased jobs per worker process, or multiple worker replicas). Leasing already fences duplicates. Keep provider rate limits in mind; B1's retry and backoff helps.

---

## §5 Upload and progress bugs (U1–U8)

Frontend: `apps/sales-xray-web/app/`. The live standalone route is `AcquisitionStudio` (`acquisition-studio.tsx`), rendered by `standalone-studio.tsx`. `workbench.tsx` and `processing-experience.tsx` are not imported by production (🔎).

### U1 — P0 — A failed or interrupted upload becomes a fake "saved call you can only delete" ✅

Found independently by two agents.

**User experience:**
1. The user picks a file and clicks Analyse.
2. The upload fails (network drop, 408, 429 or 422), or they refresh or close the tab mid-upload, or click "Analyse a call" in the nav.
3. They then see *"This saved call cannot be opened here. If you own it, you can still delete it."*
4. The consent checkbox and the Analyse button are gone. They are offered "Request deletion" for a call that **never existed**.
5. Every way out loses the selected file. This recurs on every visit until they click "Forget this saved call".

**Where:**
- `acquisition-studio.tsx:998-1001`, *before* the PUT at `:1018-1032`:

  ```ts
  const id = pending?.selection?.intentId ?? chosenId.current;
  // Only an opaque selector is remembered...
  rememberSubmission(id);
  ```

- Restore path `acquisition-studio.tsx:485-498`: any 403 or 404 on the remembered id triggers `setDeletionOnlyId(saved)` with the "cannot be opened here" error. A never-committed upload returns 404 here.
- The upload form is hidden while `deletionOnlyId` is set (🔎 `:1722-1732`, `:2170-2174`).
- "Analyse another call" drops the selected file (`reset()` → `stagedFiles.filter((candidate) => candidate !== file)`, `:1103-1105`).
- The same thing happens after a mid-upload 401 (see A4). The message there says *"Your guest session is no longer active…"* even for signed-in users (`acquisition-client.ts:85-86`).

**Fix direction:**
1. Store the id in a **pending** slot (e.g. `{ id, sha, startedAt, state: "uploading" }`) before the PUT. Promote it to "saved" only after the PUT or recovery read returns a bound submission (`:1034-1036`).
2. On restore:
   - Pending id + 404 → treat as "the upload didn't finish". Clear the pending slot silently and show the normal upload form, keeping the file if it's still in memory.
   - 403 → keep the current deletion-only path.
   - 404 on a *promoted* id → "This call is no longer available", with a Start new call button (not deletion-only).
3. Keep the existing "failed PUT may have committed" recovery read (`:1004-1017`); it is correct and important.
4. Never hide the upload form because of a stale pending id.

**Tests (vitest):** PUT rejects with a network error then reload: the upload form is visible, no deletion-only UI, and the pending slot is cleared. PUT 422: same. PUT succeeds and a later 404: "no longer available". A real 403: deletion-only is preserved.

---

### U2 — P1 — Upload errors are misleading, so users retry uploads that can never succeed ✅

**Cases:**
- **Too long.** A 70-minute call at low bitrate fits under 32 MiB, so it uploads completely. The server measures duration and fails with `measurement_duration_differs`, surfaced as *"The audio length could not be verified. Try another file."* (`acquisition_source.py:110-140`). The client maps that to `source_verification`, whose copy says **"Try again"** (`acquisition-client.ts:75-76`). The browser never checks duration, even though the page advertises "60 min per call".
- **Unsupported format with a valid extension.** The server says `"Choose a supported original audio file."` (`acquisition_source.py:53`). The client maps 422s by **exact English string** (`acquisition-client.ts:168-189`). This string isn't in the table, so the user sees the fallback *"This request did not finish. Check your connection and try again."* (`:103`).
- **Network drop mid-upload.** A `TypeError` from fetch becomes *"This result could not be verified. Try again; your completed work stays saved."* (`acquisition-studio.tsx:112-115`), claiming something was saved when nothing was.

**Fix direction:**
1. **Server:** return stable machine reason codes in the error body alongside the human text, e.g. `{"detail": "...", "reason": "source_duration_exceeded" | "source_format_unsupported" | "source_measurement_failed" | "source_incomplete" | "source_storage" | "upload_capacity_busy" | ...}`. Distinguish "longer than 60 minutes" from "could not measure". The measured duration is available at the check (`duration`, `MAX_SECONDS`).
2. **Client:** map by `reason`, not by English sentences. Give each reason a precise message and the right action ("Choose a shorter recording (max 60 min)", "Convert to MP3/WAV/M4A…", "Upload interrupted — nothing was saved. Try again").
3. **Client pre-check:** read duration via an `HTMLAudioElement` `loadedmetadata` (cheap, no decode). Block a clearly over-limit file before upload, and warn when the duration is unknown. The server stays authoritative.

**Tests:** vitest for each reason code; Python tests that the server emits the reason for each branch.

---

### U3 — P1 — Status checks stop for good after about 12 seconds of network trouble ✅

**User experience:** laptop sleep, a Wi-Fi switch or a tunnel. The page shows "Status cannot currently be refreshed" forever, **even after the report is ready**. With a `?call=` link, the whole screen becomes "Could not open your saved call".

**Where:** `acquisition-studio.tsx:747-766`:

```ts
} catch (error) {
  if (abort.signal.aborted) return;
  failures += 1;
  setStatusIssue(message(error));
  if (
    failures >= 3 ||
    (error instanceof AcquisitionError && [401, 403, 404, 409].includes(error.status))
  ) {
    setExistingCallEntry({ submissionId: bound.id, state: "failed" });
    return;                      // polling ends; nothing restarts it
  }
}
...
timer = setTimeout(() => void poll(), failures ? 6000 : 3000);
```

- `acquisition-processing-panel.tsx:100-114` listens for `online` and `visibilitychange`, but only toggles display flags (🔎).
- A `pollAttempt` state exists and restarts polling when bumped (`freshPlan()` does `setPollAttempt((n) => n + 1)`, `:1093`), but no network listener bumps it.
- Polling also runs every 3 s with no cap while awaiting approval, including in hidden tabs (🔎).

**Fix direction:**
1. Network or 5xx failures → exponential backoff (3 s → 6 → 12 → … capped at about 60 s). **Never** permanently stop, and never mark the call `failed` for transient errors. Only 401/403/404 are terminal, and 401 should route to sign-in (A9) rather than "failed".
2. Restart immediately (`setPollAttempt(n => n + 1)`) on `online`, on `visibilitychange` to visible, and on window `focus`.
3. Pause polling while `document.hidden`. Slow it down (e.g. 15 s) while awaiting user approval.
4. Keep status reads read-only (they are today).

**Tests:** vitest with fake timers: 3 network failures, then `online` event, then poll resumes and shows the report. Hidden tab: no requests.

---

### U4 — P1 — The automatic start after upload is sometimes lost 🔎 (effect code ✅)

**User experience:** after upload, the page says "Keep this tab open to finish starting analysis", then lands on "Ready to continue" with a manual button, sometimes while analysis is actually already running. The approval card can also flash with an enabled "Continue analysis" button.

**Where:** `acquisition-studio.tsx:781-859`:
- The auto-approve effect depends on `processingState` (`:858`).
- When the server creates the plan, the next 3-second status poll changes `state` from `ready` to `quoted`. That re-runs the effect, whose **cleanup aborts the in-flight get/accept and clears consent** (`:835-843`, `setConsentedSubmissionId(... null ...)`).
- Because `requestedPlan.current === submission.id` (`:793`, `:798`), it never retries.
- Separately, "Check status" and "Check again" call `setConsentedSubmissionId(null)` (🔎), so clicking them during "Checking your recording" cancels the auto-start.
- `busy` is not set during auto-approval, so the approval card's button is enabled.

**Fix direction:**
1. Remove `processingState` from the effect's dependency list. Read it through a ref for the guard.
2. Do not clear consent on a cleanup caused by a dependency change. Only clear it on explicit user cancel or on unmount. Rely on server idempotency (quote and accept are already keyed; `quoteKey`) and allow **one** automatic retry after an abort.
3. Set a `busy`/`autoStarting` flag while auto-approval is in flight, and disable manual controls.
4. "Check status" must not revoke consent.

**Tests:** vitest simulating a poll that returns `quoted` mid-accept: accept completes, or is retried once, and consent is retained.

---

### U5 — P1 — "Analysis paused" gives no reason and no way forward ✅

**Where:** `acquisition-studio.tsx:98-110`:

```ts
function pausedFailureMessage(failureCode: string | null): string {
  if (failureCode === "conversation_broker_service_identity_unavailable" || ...) return "The approved provider credentials are unavailable...";
  if (failureCode?.startsWith("conversation_provider_http_")) return "The approved provider returned an error...";
  return "";          // every other code shows nothing
}
```

- Codes that get an empty message include `stage_failed`, `stage_uncertain`, `conversation_provider_execution_timeout`, `processing_authorization_or_input_unavailable` and all `report_*` codes.
- Polling stops when the plan is `held` (`:727-735`).
- "Review and continue analysis" is only offered when C2 is complete (🔎 `acquisition-processing-panel.tsx:273-274`).

**Fix direction:**
1. Map **every** failure code the backend can emit, including the new specific ones from B1, B5, B6 and B7, to plain language + what happens next + one action button + the request or call reference. Examples:
   - A provider-returned error being retried automatically: "The AI service was busy. We'll retry automatically — no need to re-upload."
   - An uncertain outcome: "We're confirming the result with the AI provider; you won't be charged twice. We'll update this page." (Keep polling at a slow rate.)
   - `plan_approval_expired` → "Your approval expired. Review and continue."
   - Validation failures → "The AI's report didn't pass our evidence checks. [Retry analysis]" (enabled by B2).
2. Default copy for unknown codes: "Analysis paused. Your recording is saved. Reference: <id>. [Contact support]". Never an empty string.
3. Keep polling (slowly) while held, so recovery done by the backend or an admin shows up without a refresh.

---

### U6 — P2 — Calls held for account or profile issues show "processing" forever 🔎

**Where:**
- The server sets `execution_hold: "account_profile_required"` (`acquisition_reports.py:455-478`; `processing_plan.py:1213-1220` sets `failure_code: "account_profile_required"` while the plan stays `active`).
- The client's progress parser drops `execution_hold` (`acquisition-client.ts:411-453`).

**Effect:** the user sees "Checking your recording…" or "Queued" indefinitely, polled every 3 s, with no hint to complete their profile.

**Fix:** parse `execution_hold` and show "Complete your AC profile to continue", with a link into the profile step (mind A8).

---

### U7 — P2 — One upload at a time across the whole server ✅

**Where:** `packages/python/ac_platform/http/conversation_submissions.py:161` `capacity = anyio.CapacityLimiter(1)`, acquired with `acquire_nowait()` at `:439-442`:

```python
raise fail(429, "Another recording is uploading. Retry shortly.")
```

- It is held for the whole upload plus native measurement.
- The API runs a single uvicorn process (`infra/application/Dockerfile.python:56`, no `--workers`, 🔎).
- Client copy: *"Another call is uploading. Please try again shortly."* (`acquisition-client.ts:99-100`) reads like the user's *own* call. There is no auto-retry, and the natural "Check again" click leads into U1.

**Fix direction:** make capacity configurable (≥ 2–4, bounded by scratch disk and native helper capacity). Wait with a short timeout instead of failing instantly. Return `reason: "upload_capacity_busy"` with `Retry-After`. The client auto-retries with backoff and shows "Server busy — retrying automatically…".

---

### U8 — P2 — Smaller progress issues 🔎

- `quoted` (plan) and `awaiting_upload` (recording) are missing from the client's `known` state lists (`processing-state.ts:56-69`, `:108-121`). A restored call awaiting approval shows the heading "Checking analysis status" instead of "Ready for your approval".
- The guest Turnstile path is unreachable in production. The edge proxy's account check blocks the guest session request, and the standalone app requires sign-in first. Confirm the intended guest policy (§10 Q5), then either remove the dead path or restore it deliberately.

---

## §6 Report and playback bugs (R1–R10)

**Do the §0 merge first; R1 and R2 are fixed on `v02-intake`.**

### R1 — P1 — After a clicked moment ends, Play pauses again almost at once ✅ (fixed on v02 ⚠️)

**Tip code** (`acquisition-studio.tsx:1243-1257`, `:2740-2749`):
- `seek()` sets `moment`.
- The dock's `onTimeUpdate` pauses whenever `currentTime >= moment.end_ms/1000`.
- `moment` is cleared only by `onSeek` and `reset()`. The dock's Play (`call-audio-dock.tsx:44-57`) doesn't clear it.

This breaks "click a transcript line and keep listening".

**v02 fix:** `onPlay` prop on the dock, called only from the dock's Play control, wired to `setMoment(null)`. Keep that fix through the merge. Add a vitest: seek a moment → it plays to the end and pauses → press Play → playback continues past `end_ms`.

### R2 — P1 — In the default Reading view, the Overview's "Open review" and "View plan" buttons do nothing ✅ (fixed on v02 ⚠️)

**Tip:**
- `dipak-overview.tsx:393-396` `focusInsight()` does `if (!showHeading) return;`.
- The dialog only opens when `open={!reading && Boolean(activeChapter)}` (`:792`).
- Acquisition passes `showHeading={false}` (`acquisition-studio.tsx:2661`), and Reading is the default mode (`report-modes.tsx:46-49,78-80`, 🔎).

Result: all 5 dashboard cards, 14 review-point buttons and the takeaway buttons are dead. **v02 fix:** `navigateToReport("overview", number)`. Add a reading-mode test; the existing test only covers the non-reading mode (`dipak-overview.test.tsx:95+`).

### R3 — P2 — Reading view renders the overview twice, with conflicting counts ✅ (still in v02 ⚠️)

- `dipak-overview.module.css:53-57` hides `.resultLead` and `.takeawayGrid` only when `data-compact="true"`.
- `data-compact={!showHeading && !reading}`, so in Reading view they render **under** `OverviewDashboard`: 4 metrics twice and 5 takeaway cards twice.
- "Source moments" uses `countReportMoments` (every excerpt), while "Source-linked moments" uses `rewatch.length` (at most 3).

**Fix:** decide which component owns the summary in Reading view and hide the other; use one count definition.

### R4 — P2 — Audio controls are locked while a review sheet is open ✅

- `review-dialog.tsx:75` calls `element.showModal()`, which makes everything outside the dialog inert, including the dock.
- Play buttons inside the Overview dialog (`dipak-overview.tsx:435`) and Next-call dialog (`next-call-plan.tsx:88,263`) start audio but leave the sheet open, so the user can't pause, scrub or change speed.
- Sales Skills (`sales-skills.tsx:235`) and Moments (`report-moments.tsx:272`) close the sheet first, so behaviour is inconsistent.

**Fix:** either close the sheet on play consistently, or render a compact player inside the sheet, or use a non-modal dialog with a focus trap that excludes the dock.

### R5 — P2 — Evidence waveforms look nearly empty on long calls ✅/🔎

- **Backend:** `signals.py:470` sets `stride = ceil(rows_per_channel / max_plot_points)` (≤ 1200 points). At `:500`, it keeps one 40 ms frame per stride (`if (index // channels) % stride == 0`), **sampling, not max-pooling**.
- **Frontend:** `source-waveform.tsx:297-317` spreads the points inside a quote's window across 96 bins (🔎).
- **Effect:** in a 60-minute call, points are about 3 s apart. A 5 s quote shows 1–2 bars, a quote under 3 s is blank, and the dock's played/unplayed colouring jumps in about 37.5 s steps.

**Fix:** max or RMS pooling per stride window on the backend, and/or a windowed endpoint (`?start_ms&end_ms`) for evidence-sized waveforms. The frontend should interpolate or hold the nearest value instead of leaving gaps.

### R6 — P2 — Every waveform re-renders about 4 times a second during playback ✅

- `source-waveform.tsx:101-126`: the provider calls `setCurrentTimeMs` on every `timeupdate` and passes a fresh `value={{ envelope, currentTimeMs }}` object.
- Every mounted `SourceWaveform` (dozens in the Overview, including inside closed `<details>` and hidden tabs) re-renders and recomputes bins over up to 1200 points. Expect jank on mid-range phones.

**Fix:** memoise bins per `(envelope, start, end)`. Split context into a static envelope context and a time store read via `useSyncExternalStore` with a selector. Or only let the visible or active waveform subscribe to time. Throttle to `requestAnimationFrame`.

### R7 — P2 — No visible playhead when the waveform is unavailable 🔎

- The dock's seek `<input>` is `opacity: 0` (`call-audio-dock.module.css:78`), and the fallback is a flat 2 px line (`.unavailable`).
- The waveform endpoint returns 409 when measurements are missing (`measurement_view.py:194-200,419-420`), e.g. legacy or unmeasured calls. The user can't see or drag the playhead.

**Fix:** a visible progress bar and thumb in the fallback state.

### R8 — P2 — Dead "Playback" button on mobile when a report is shown ✅

- `acquisition-studio.tsx:1376` sets `const audioPlayer = !reportReady ? (<audio …/>) : null`.
- But the toggle still renders (`:2113-2127`, `"Hide player" : "Playback"`), and it is visible at ≤ 760 px (`acquisition-studio.module.css:1591`, 🔎).
- Tapping it opens an empty area.

**Fix:** hide the toggle when `reportReady`, since the dock replaces it.

### R9 — P2 (scalability) — Audio streaming holds a DB connection per listener; seeks re-hash the whole file ✅/🔎

- **DB connection:** `http/conversation_submissions.py:312` `streaming_dependency = Depends(read_only_owner, scope="request")` holds the owner-check transaction and pooled connection for the whole response, up to `asyncio.timeout(180)` (`http/conversation_playback.py:73-76`). With `preload="metadata"`, browsers often keep that response open. The default SQLAlchemy pool (5 + 10, `db/session.py:10`, 🔎) can starve with modest concurrent listeners.
- **Every range request re-hashes the full object:** `conversation_intelligence/storage.py:486-494` reads the whole file through SHA-256 (up to 128 MB). It then iterates blocks from byte 0 up to the range start (`conversation_playback.py:54-64`: `offset` walks forward through `next(source)` without seeking).

**Fix:**
1. Do the owner check in a short-lived session, release it, then stream.
2. Verify the digest once (at upload or first read) and cache the verification by `(object id, size, mtime)`.
3. `seek()` to the range start instead of iterating.

Keep the deletion and mutation fences (#63 mentions a deletion-serialization design; don't break it).

### R10 — P3 — Minor 🔎

- Sheets don't push a history entry, so Android Back leaves the report instead of closing the sheet.
- Moment timestamps use `formatTranscriptTime` (e.g. `32:15.480`), while the Overview uses `mm:ss`. Pick one user-facing format.

Checked and fine (don't spend time here):
- Missing overview, empty findings, moments or strengths are handled.
- The dock stays mounted across tab and mode switches.
- Section navigation uses `replaceState`.
- Long text wraps (`overflow-wrap: anywhere`).
- No client-side audio decoding.

---

## §7 Sign-in, account and library bugs (A1–A9)

Re-check after the §0 merge: `4f1d7a04`, `0e0eca6e`, `e03794be` and `f84dbe0c` touch this area.

### A1 — P1 — You can't back out of the in-page sign-in screen on `/` ✅ (still in v02 ⚠️)

- `account-auth.tsx:620` (logo) and `:693` ("Return to app") are `<Link href="/">`.
- The screen is shown from `standalone-studio.tsx:336-340`, `:450-453` via `authRequested`. That flag is only cleared in `onCancel` (not passed when no file is selected) and in `onAuthenticated`.
- A link from `/` to `/` preserves component state (Next 16 `layout-router`), and so do search-param changes.
- Result: the user is stuck until they reload.

**Fix:** always pass an `onCancel` that clears `authRequested`, and render "Return to app" as a button calling it.

### A2 — P1 — Signing in from `/login` always drops you on `/` ✅

- `login/page.tsx:10` does `window.location.assign("/")`, and the server only accepts `"/"` as the Sales Xray return path (`auth.py:1411`, 🔎).
- Links into `/login` come from:
  - saved-call recovery: "Sign in to recover it" (`acquisition-studio.tsx:1484,1560,1763`)
  - the library's "Sign in" (`calls-library.tsx:251`)
- So a signed-out user opening a `/?call=<id>` link signs in and lands on the empty upload page, and `/calls` → sign in → `/`.
- The pre-sign-in copy is also wrong. It says *"That saved call belongs to another browser session"* (`acquisition-studio.tsx:476`) when the user is simply signed out.

**Fix:** support a validated same-origin `returnTo` allowlist (`/`, `/calls`, `/?call=<uuid>`) end to end, client and `auth.py`. Reject anything else, to avoid an open redirect. Fix the copy.

### A3 — P1 — After "Change email", "Send sign-in code" silently does nothing for up to 60 s ✅

- `account-auth.tsx:176-185`: the handler returns early when `Date.now() < retryAt`, with no message.
- "Change email" (`:992-996`, 🔎) doesn't reset `retryAt`, and the Send button stays enabled (`:865`, 🔎).
- Mistyped emails on mobile are common, so users will hit this.

**Fix:** reset `retryAt` on email change (the per-address server limit still protects), or show a visible countdown and disable the button.

### A4 — P1 — A 401 or failure mid-upload leaves a phantom call and throws away the file 🔎

This is the same root cause as U1, reached via auth.
- `rememberSubmission(id)` is called before the PUT (`acquisition-studio.tsx:1001`).
- The session is revoked (e.g. signed out in another tab), so the PUT returns 401.
- The copy says "guest session no longer active" for signed-in users.
- The "Sign in" link (`:1763`) does a full navigation, which drops the selected file. The in-page sign-in, which keeps the file, isn't used.
- After signing in, the stored id returns 404, which produces the U1 deletion-only screen.

**Fix:** U1, plus using the in-page `AccountAuth` for the mid-flow 401 and correct copy by auth kind.

### A5 — P2 — After an OTP lockout, "Resend code" says success but no email arrives for up to an hour 🔎

- `identity/email_login.py:227-236` returns `None` when `failed_attempts >= 5`, or after 5 sends in the hour. The endpoint still replies `accepted: true`.
- The client resets its timers and says "Check your email" (`account-auth.tsx:228-234`).
- Typing an old code after a resend counts as a failure.

**Fix:** keep the response non-enumerating for unknown addresses, but for the *current* challenge return a generic "Too many attempts — try again in N minutes or use password sign-in" state. `e03794be` on v02 surfaces a password fallback; build on it.

### A6 — P2 — The loading screen can spin indefinitely 🔎

- `standalone-studio.tsx:120-134`: the `/v1/me/workspaces` check has no timeout.
- The preloader (`:518-525`) is only given `phase="session"`, so its existing `"delayed"` and `"error"` phases never show.

**Fix:** a 10–12 s timeout (the studio already uses 12 s for its own setup), then `"delayed"` with Retry, then `"error"`.

### A7 — P2 — Google sign-in dead ends 🔎

- **Popup closed early** (`account-auth.tsx:454-482`): nothing checks `child.closed`, so the form is disabled until Cancel or a 5-minute timeout (`:527-530`). "I finished Google sign-in" says "Finish sign-in in the Google window" when there is no window.
- **Opened in the same tab** (in-app browsers): `/auth/complete` has no link back, and "Close this window" does nothing (`auth-complete-client.tsx:64-92`), though the user is signed in.
- **In-app browsers:** there is no detection or guidance for LinkedIn, Instagram, etc., where Google blocks embedded sign-in.
- **Slow return:** the completion receipt TTL is 180 s (`http/auth_transactions.py:20`), so a slow mobile return shows "could not be confirmed" even though the cookie was set.

**Fix:**
1. Poll `child.closed` and reset the form.
2. On `/auth/complete` without an opener, redirect to the validated `returnTo`.
3. Detect in-app user agents and show "Open in your browser" guidance.
4. On an expired receipt, re-check the session before showing the error.

Re-check against `4f1d7a04` and `0e0eca6e` first.

### A8 — P2 — The profile step dead-ends for accounts outside the public learner workspace 🔎

- `standalone-studio.tsx:472-477` shows the profile form whenever an identity exists, including in chooser and empty states.
- The profile endpoint returns 403 unless the session's workspace is the public learner workspace (`http/sales_xray_profile.py:83-87`).
- `account-profile.tsx:204-212` treats the 403 as a generic error with a Retry that loops forever, and the workspace chooser is unreachable while a file is selected.
- Mostly staff, coaches and multi-workspace users, which means your internal testers.

**Fix:** on 403, route to the workspace chooser or explain "Switch to your learner workspace", and never offer an infinite Retry.

### A9 — P2 — An expired session in the library loops on a generic error 🔎

- `calls-library.tsx:119-126`, `:185-191`: after signing out elsewhere, `/calls` or "Load more" shows "Saved calls could not be loaded. Try again…". Retry repeats the 401.
- The header still says "AC account / Sign out", because the session is never re-checked.
- Returning to `/calls` from a call reloads from scratch, losing loaded pages and scroll position.

**Fix:** on 401, re-check the session, switch the header to signed-out, and show Sign in (with `returnTo=/calls`, A2). Cache the loaded pages and scroll position in memory for back navigation.

Checked and fine:
- Logout returns 204 and clears the stored call id.
- The library cursor format is accepted.
- Deleted calls disappear immediately.
- Claim is idempotent, and an unrelated guest cookie doesn't block own-call reads.
- A file picked before the in-page sign-in survives.
- Cookies are SameSite=Lax and host-only, correct for the Google callback.

---

## §8 Live production observations (guest surface only)

Checked `https://salesxray.authorityclosers.com` on 24 Sep in a clean browser as a guest (desktop and 375 × 812 mobile). No upload was made, to avoid spending provider budget or creating customer data.

- The landing, `/calls` (signed-out state) and `/login` render correctly, with no horizontal overflow on mobile.
- The CSP blocks the Cloudflare Web Analytics beacon: *"Loading the script 'https://static.cloudflareinsights.com/beacon.min.js/…' violates … script-src 'self' 'unsafe-inline' https://challenges.cloudflare.com"*. Either allow it in the CSP or disable the Cloudflare beacon injection. Right now analytics silently don't record.
- `GET /v1/conversation/acquisition/availability` fires about 4 times on one landing load. Dedupe it.
- Desktop landing shows the limits twice ("MP3 · … Up to 32 MB · 60 min per call" and again "Up to 32 MB · 60 minutes per call").
- For guests, `/v1/me/workspaces` and `/v1/conversation/acquisition/session` return 401, which is expected but noisy in the console.
- Staging (`salesxray-staging.authorityclosers.com`) was not exercised.

---

## §9 Verification plan and definition of done

Per PR:
1. Unit and vitest coverage for every bug fixed, as listed per item.
2. **PostgreSQL** integration tests for anything touching the ledger, reservations, plans, tasks or retry (B1, B2, B3, B6, B7). Use the existing disposable-schema pattern.
3. `pnpm --filter @ac/sales-xray-web typecheck && pnpm --filter @ac/sales-xray-web lint && pnpm --filter @ac/sales-xray-web test`
4. Python focused suites (Appendix B), then the full CI shards.
5. The compiled browser gate `test_compiled_guest_upload_report_reload_claim_and_deletion` must **run, not skip** (the 22 Sep audit found it skipped; #63 says it is now required, so confirm in the run log and JUnit).

Journey acceptance on staging, with synthetic or fictional provenance-cleared audio only (`AGENTS.md` #12):
- Upload → report → reload → citation playback → keep listening past a clip (R1) → library reopen.
- **Fault injection:**
  - a provider 429 or 503 on C2, C4 and C5 each (auto-recovers, B1)
  - a held plan → fresh plan → report (B2)
  - a bundle re-issue mid-run (B6)
  - network loss for 30 s mid-processing (U3)
  - PUT interrupted then reload (U1)
  - a 70-minute file (U2)
  - two concurrent uploads (U7)
- Budget: N calls consume roughly actual cost, not worst case (B3). The backfill dry run on staging shows paise to be freed.
- 20 consecutive fresh end-to-end attempts with no unhandled stall, wrong owner, duplicate charge or wrong evidence link (RECOVERY_PLAN §5 target). Record the sample size, retries, cost and p50/p95 honestly.

**Done means:** a user uploads once, sees truthful progress, and gets a source-bound report they can reopen and listen to comfortably. When a provider hiccups, the system recovers by itself without double-charging. When it can't, the user sees why and has exactly one sensible next action.

---

## §10 Questions that need the founder or controlled documents

Do not guess these (`AGENTS.md`: "Do not infer protected business semantics").

1. **B3:** Should settlement use approved token or minute rates times provider-reported usage, or provider invoices? Are provider HTTP 5xx and 429 treated as no-charge for **each** provider (Gemini, Groq, Deepgram, ElevenLabs)?
2. **B1/B2:** Should automatic retries of *provider-returned* failures count against the user's trial minutes or per-source allowance? Proposed: no.
3. **B4:** May one MAX_TOKENS repair at a higher limit run within the already-approved plan budget, or does it need a new approval?
4. **B6:** Which bundle changes are "compatible" with an in-flight accepted plan (adding testers or allowance: yes; lowering caps or revoking a user: no)? What should the execution deadline be per call length?
5. **U8:** Is a guest (no-account) upload intended in production? The Turnstile code exists but is unreachable.
6. **U7:** What is the acceptable concurrent-upload capacity on the current VPS (scratch disk, native helper)?

---

## Appendix A: file index (paths at `4bbc2b79`)

Backend, `packages/python/ac_platform/`:
- `conversation_intelligence/inference_worker.py`: dispatch, `_fail`, `_VALIDATION_FAILURES`, `provider_failure_code` (B1, B3, B5, B6)
- `conversation_intelligence/inference_broker.py`: stable error codes, `provider_http_NNN` (B1)
- `conversation_intelligence/providers.py`: HTTP call, non-200 → `provider_http_<status>` (B1)
- `outbox/repository.py`: `fail()` at 2059; retryable no-effect path at 700-707 (B1)
- `conversation_intelligence/entitlements.py`: `mark_dispatched`/`mark_uncertain`/`settle`/`release`, `committed_paise` (B1, B3)
- `conversation_intelligence/processing_plan.py`: authority check 378-392, budget 841-844, expiry 881, `_enqueue` 996-1017, hold 1221-1226, generic hold 1280-1293 (B2, B3, B6)
- `conversation_intelligence/checkpoints.py`: `cache_key` with the unused `replicate` field (B2)
- `conversation_intelligence/reports.py`: numeric key regex 167-170/877-881, evidence-missing 1509-1511, `REPORT_VALIDATOR_REVISION` 1524 (B5)
- `conversation_intelligence/report_overview.py`: `stage_completion_limit` 21-31 (B4)
- `conversation_intelligence/gemini_tasks.py`: generation config 55-73, finishReason check 313 (B4, B5)
- `conversation_intelligence/contracts.py`: `C5_REPAIR_FAILURE_CODES` 61-75 (B4, B5)
- `conversation_intelligence/acquisition_source.py`: format 53, duration 105-140 (U2)
- `conversation_intelligence/acquisition_reports.py`: progress serialization, `execution_hold` (U5, U6)
- `conversation_intelligence/signals.py`: waveform stride sampling 466-503 (R5)
- `conversation_intelligence/storage.py`: full-file hash per read 486-499 (R9)
- `http/conversation_submissions.py`: upload limiter 161/439-442, streaming dependency 312 (U7, R9)
- `http/conversation_playback.py`: range streaming 48-79 (R9)
- `identity/email_login.py`, `http/auth.py`, `http/auth_transactions.py`, `http/sales_xray_profile.py` (A2, A5, A7, A8)

Frontend, `apps/sales-xray-web/app/`:
- `acquisition-studio.tsx`: `pausedFailureMessage` 98-110, restore 455-500, polling 700-770, auto-approve 781-859, upload 995-1052, `freshPlan` 1083-1096, `seek` 1243-1257, `audioPlayer` 1376, Playback toggle 2113-2127, dock wiring 2736-2752 (U1–U5, R1, R8)
- `acquisition-client.ts`: error copy 70-105, 422 mapping 168-191, progress parser 411-453 (U2, U6, U7)
- `acquisition-processing-panel.tsx`, `processing-state.ts` (U3, U5, U8)
- `call-audio-dock.tsx`, `source-waveform.tsx`, `review-dialog.tsx`, `dipak-overview.tsx`/`.module.css`, `report-modes.tsx`, `next-call-plan.tsx` (R1–R8)
- `account-auth.tsx`, `login/page.tsx`, `auth/complete/*`, `standalone-studio.tsx`, `account-profile.tsx`, `calls-library.tsx` (A1–A9)

Prior evidence: `D:\Projects\authority-closers-platform\docs\evidence\sales-xray-audit-20260922\` (`RECOVERY_PLAN.md`, `independent-findings.md`, `live-status.json`). These are untracked in the primary checkout.

## Appendix B: test commands

Python (the investigated worktree has no `.venv`; the audit used `D:\Projects\authority-closers-platform\.venv` with the worktree first on the path, or create a venv per the repo's setup):

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/unit/conversation_intelligence/test_reports.py tests/unit/conversation_intelligence/test_report_overview.py tests/unit/conversation_intelligence/test_retained_c5_recovery.py tests/unit/conversation_intelligence/test_inference_failure_diagnostics.py tests/unit/conversation_intelligence/test_processing_plan.py tests/unit/conversation_intelligence/test_inference_tasks.py tests/unit/conversation_intelligence/test_inference_broker.py tests/unit/conversation_intelligence/test_inference_worker_stages.py tests/unit/conversation_intelligence/test_retained_c2_recovery.py tests/unit/conversation_intelligence/test_report_structure.py tests/unit/conversation_intelligence/test_report_language_contract.py
```

Web:

```powershell
pnpm --filter @ac/sales-xray-web typecheck
pnpm --filter @ac/sales-xray-web lint
pnpm --filter @ac/sales-xray-web test
```

Ruff and formatting per the repo's CI (`.github/workflows/application.yml`).
