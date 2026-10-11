# AUT-1677 — Recover stalled Prospect reads

The Prospect list and profile GETs previously relied on a caller's cancellation
signal. Neither page supplied a deadline. An unavailable service could leave the
initial skeleton or pagination request pending indefinitely. The focused
pre-change check reproduces this for both pages: a deliberately stalled fetch
is still pending after 15 seconds.

The existing list/detail clients now bound the whole read to one 15-second
deadline, including response headers and success/error JSON. Scope cancellation
also ends the read even when a defective adapter ignores AbortSignal. A scope
already cancelled sends no private GET. Timers and parent listeners are removed
after every completion, and the internal fetch/body is cancelled without
aborting the caller's scope. Late responses cannot replace a settled failure.

The existing pages handle the failure through their small corner card and
explicit Try again action. The skeleton clears, customer data remains hidden,
and a successful fresh read restores the populated list or six-section profile.
There is no automatic retry. The same GET clients cover pagination and Report
key-fact detail reads. Human edits/confirmations, permission policy, source
parsers, identity checks and server data are unchanged.

Verification:

- All 64 focused read/client/list/profile/snapshot cases pass. Fourteen read
  cases cover stalled headers, success/error JSON, one shared deadline, late
  results, scope loss, pre-cancelled scope, and successful cleanup. Two page
  cases use the real clients to prove skeleton clearing, corner retry and
  restored fictional data. Existing status, identity, profile and access-loss
  cases remain in the same passing run.
- Incremental TypeScript, cached changed-file ESLint, Prettier and browser-script
  Ruff/format pass. Shared-dev browser proof follows the
  committed refresh; its receipt and screenshot observations are recorded in
  `/home/acdev/strikes/1677/NOTES.md`.
- The shared-only browser runner exercises native stalled HTTP reads at
  390/1440 in light/dark. It intercepts all API reads locally using invented
  values, rejects writes/unexpected routes, and starts no build/server. It
  checks no automatic retry, loading clears, explicit recovery, six sections,
  44px phone retry, overflow and page errors.

The existing AC-UXA-01 recovery and asynchronous-status requirements apply.
This bounded read repair does not activate providers, schema or persistence.
Production Report acceptance, saved-call route adoption and canonical
Company/outcome storage retain their recorded H/QA, A and C/E dependencies.

The first shared attempt verified the desktop light list timeout/retry and
captured two PNGs, then failed its profile-skeleton precondition: toggling
access for the same already-loaded profile retains that view's data. The
corrected runner unmounts the profile through the list before stalling a fresh
profile GET. The partial attempt is preserved separately and is not a complete
browser pass. Final committed-source verification remains required.

Inspection of those partial desktop screenshots also found that Try again
wrapped and the corner card's maximum width excluded padding. The existing
owned Prospect corner-card style now includes padding in its width, lets the
message wrap and keeps its action on one line. The browser proof checks actual
card insets/width and non-wrapping action text at both viewports and themes.

The next attempt reached the fresh profile's deadline, then failed a counter
that assumed exactly one mount GET. Shared dev may replay an initial effect.
The final runner records the initial dispatch count after it settles and checks
that no additional request occurs before/after the deadline failure; the user's
explicit retry must add exactly one GET. This preserves the no-automatic-retry
assertion without confusing an initial mount with a retry. Partial attempts
remain separately recorded, never counted as complete acceptance.
