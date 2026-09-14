# Sales Xray provider import and release verification

The Admin settings screen now imports an existing reviewed non-secret registry
configuration through the same revision-safe API as its form editor. Local JSON
validation shows the canonical digest, models, routes and per-dispatch ceilings.
Saving and activating remain separate operations. Stale revision conflicts keep
the selected configuration for review; editing while a digest or file read is
pending invalidates the older result. A late save response can only confirm the
same imported digest. Credentials are neither entered nor stored by this flow.

Integrated leaves: `56d40f2`, `48cb7e3`. The saved-call recovery change is documented
in `20260914_SALES_XRAY_HELD_CALL_RECOVERY.md`.

Validation on the integrated candidate: 14 provider-control tests, 27 acquisition
workflow tests, both app typechecks, targeted formatting and Admin lint passed.
The leaf Admin production build passed. Candidate CI and deployment remain
required; these local results do not establish production behavior.

At 2026-09-14 15:47 UTC, the preceding `fc7dc868` release was live in both
environments. A real approved production excerpt uploaded through the standalone
UI, passed local checks and completed ElevenLabs C2 and Gemini C4. C5 returned a
complete response but failed report validation. Its private response was retained
for offline diagnosis; no completed report or end-to-end launch approval is
claimed. Production Admin displayed this guest recording, stage states and a
partial usage estimate distinctly from reservation ceilings and unsettled actual
charges. Private call content and identifiers are excluded from this repository.
