# AUT-1677 — ready Reports do not wait for optional Coaching

`preloadSavedReport` previously awaited transcript, Report and optional Coaching
together. A stalled Coaching read could add its entire 1.5-second deadline to
opening a Report whose native transcript and analysis were already available.

The required source reads still run together after the canonical submission
read. Optional own-call Coaching starts alongside them and is included only if
its payload has arrived by the time the required reads finish. The existing
call/person/tenant/session/source/revision parser still validates that payload.
A pending optional read is cancelled when the helper returns; late resolution
or failure cannot change the returned Report. The existing Coaching view has
its own authorised reader when no bootstrap is ready.

Focused tests hold both clocks and the optional deadline signal still. The
Report returns ready and cancels its pending Coaching read without any timer
advancement. Further tests cover ignored late success/failure, fast parallel
bootstrap retention, malformed/missing optional data, native source mismatch,
report digest pin, overall timeout and page cancellation. Typecheck and cached
changed-file lint/format verify the exact helper and tests.

This removes the helper's optional read from the critical path; it does not
establish deployed load time. Strike A still owns the saved-call route/studio
adoption and server API-origin configuration. No provider, pipeline, persistent
data, authentication, dependency or deployment behavior is changed.
