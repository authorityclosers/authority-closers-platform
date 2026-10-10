# AUT-1677 — saved Report preload boundary

Source pin: main `4d623da`; retained Report implementation `94d0807`. Owner asks for server-loaded saved calls with a first-paint skeleton and no processing steps for a finished call.

`app/report-preload.ts` supplies `preloadSavedReport(callId, authorisedGet, signal)`. It makes one canonical submission GET, then parallel retained C2/C5 GETs only for `has_report`. It reuses existing submission/progress/transcript/report parsers and verifies call, recording, source hash and transcript revision. There is no approval, execution, provider request, detection write or shared cache. Missing fields/routes, stale sources and adapter failures return a generic unavailable result instead of throwing. A total 15-second deadline and caller cancellation also bound adapters that ignore AbortSignal. A nonfinished call returns its canonical progress/failure fields unchanged.

The route owner must supply a GET port bound to the current authorised session/workspace, exact configured internal API origin, no-store, redirect rejection and the supplied signal. No origin, credential or header from query/client props; no cookies or private error bodies in returned props. This module adds no sign-in or auth behaviour.

Strike A owns `/analysis/calls/[callId]` and AcquisitionStudio. Required wiring: initialise submission/progress/result together from a request-scoped verified ready result; skip redundant status/report reads and processing/plan panels for that ready result. Keep current recovery/polling for canonical nonfinished calls and corner retry for unavailable. Bind the bootstrap to call/person/tenant/session and invalidate it on account/workspace changes. Add the route first-paint skeleton and verify actual dev opening. Until wired, this is a tested handoff, not an instant-opening product claim.

Verification:

- 11 preload tests: parallel reads, canonical queued state, missing fields, submission/C2/C5 identity/revision/content mismatches, invalid path input, sanitized adapter errors, deadline and cancellation. All pass.
- Customer detail fetch now verifies the returned prospect ID matches the requested ID and rejects redirects, protecting Key facts from a valid but misbound response. Its regression and the other customer/facts tests pass (23 tests).
- Owner-corrected retained navigation and explicit Story playback assertions pass, with one fixed audio dock. The affected upload/report, dock/Story and fictional shell cases pass. Other acquisition cases passed in the focused integration run before this selector correction.
- The fictional shell passes a null call binding to Key facts, so its synthetic identity triggers no server prospect read. This is a one-prop fixture-only change, with no other strike PR overlap at the checkpoint.
- App typecheck, changed-file ESLint and diff check pass. Full compiled acquisition/browser at `94d0807` passes in CI. Latest-head complete CI remains required.

Durable route wiring details: `/home/acdev/strikes/1677/saved-report-preload-handoff.md`. Companies schema/Pulse mapping preparation: `company-schema-plan.md` and `/home/acdev/strikes/pulse-people-roles.md` Mode B. Company migration is waiting for the single shared-file slot held by PR #429; no Companies API/list/schema or live provider activation is claimed.
