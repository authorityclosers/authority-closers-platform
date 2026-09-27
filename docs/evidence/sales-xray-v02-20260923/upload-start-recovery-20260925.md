# Upload-to-analysis recovery — 25 September 2026

Source baseline: `2de44e783943be936615d88b60b6912a7d74e810`. This record covers the frontend patch, not a deployment or a new provider execution.

## Observed problem and causes

The owner supplied mobile screenshots showing a saved upload followed by a failed request and a separate plan-review/continue sequence. A bounded staging request-log lookup confirmed HTTP 422 on the owner submission's `POST /plan/quote`; that event did not record an error reason.

The source path establishes a reproducible defect: Hindi and Marathi language codes contain `+`, and the automatic quote key appended that code literally. The quote route calls `GuestOwnership.ensure_processing_continuation` before planning; its request-key whitelist excludes `+`. A manually requested fresh plan uses a UUID key, explaining why that path can succeed. This is source corroboration, not a claim that the log recorded the rejected character.

A separate effect dependency could abort the pending automatic start when progress changed from queued to active. Cleanup cleared the upload's automatic-start consent binding and left an unnecessary manual approval step.

## Changes

- Normalize `+` to `_` only in the bounded language-specific request key. Preserve the selected language unchanged in the quote body and saved plan.
- Depend on terminal/nonterminal progress rather than every progress-state string while a quote is pending.
- On an ambiguous acceptance response, read the saved plan once. Confirm acceptance only for the same recording, plan ID and fingerprint. Never automatically submit another acceptance or provider attempt.
- Provide a direct **Start analysis** / **Retry analysis** action for an eligible saved call. Reuse the quote and acceptance identity; repeated clicks share the operation guard.
- Keep errors and recovery controls before the processing/file details. Replace obsolete plan-review wording for the ordinary ready-to-start state.
- Preserve explicit review for changed plans, language mismatches, held work and restored-call consent. Preserve server allowance, privacy, execution-pause and ownership checks.

## Validation

Node 24.19.0 / pnpm 11.19.0:

- Focused Vitest run: **108 tests passed** across acquisition studio, processing panel, processing state, status copy and shell navigation.
- Sales Xray TypeScript check: passed.
- ESLint on the nine changed implementation/test files: passed with zero warnings.
- `git diff --check`: passed.
- Independent source review confirmed the key-validation chain, stable effect dependency and exact-plan reconciliation. Added the reviewer's requested same-ID/different-fingerprint rejection regression.

The tests include all three report languages, an interrupted quote, progress changing during a pending quote, lost acceptance responses, wrong saved plan IDs/fingerprints, rapid repeated retries, no second upload, GET-only status checks, stale-plan review and existing held/paused flows.

Local Chrome checked the actual acquisition component with synthetic in-tab API responses and a one-second silent WAV. At 390×844, the error occupied y=163–288 and the retry button y=234–276, without horizontal page overflow. A retry reached the transcribing state with one acceptance POST and one source PUT across the session. The first fixture version had incorrect source-hash and cost-label fields; these were corrected before the successful recovery check. This is limited local UI evidence, not a clean real-provider end-to-end run. The temporary browser fixture was removed; no provider request or hosted data mutation was made.

## Release acceptance still required

Package the exact integrated revision, pass required CI, then verify an authorized small call on staging and production. Check one upload action through the saved playable report, Calls refresh, mobile recovery visibility and no duplicate charged work. The full v0.2 release remains incomplete until those deployed checks pass.
