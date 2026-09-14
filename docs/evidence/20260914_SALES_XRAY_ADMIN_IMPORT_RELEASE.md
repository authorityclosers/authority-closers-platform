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

The next integrated core run `34865939866` failed one Admin test: its assertion
ran before the asynchronous model-configuration digest completed. The app's
request and revision contract were unchanged. Commit `606806d` waits for the
actual POST inside React `act`; the full Node 24 Admin suite then passed all
823 tests, with lint and formatting passing. This supersedes the failed local
timing assumption; the failed CI run remains evidence and is not a release.

Production new-analysis execution was paused through the authenticated Admin
control after the failed real report. Existing recordings, completed C2/C4,
review inventory and budget holds remain intact. Resume is required after the
corrected source passes CI and the canonical installer, followed by a new
bounded plan and an actual report readback. The complete C5 audit and prompt
correction are recorded in `20260914_SALES_XRAY_C5_ROOT_TYPES.md`.

The launch acceptance includes the standalone and embedded learner journeys,
source-bound report/evidence playback, Admin call inventory and provider
configuration, and a visible distinction between reserved ceilings and actual
settled costs. Cached transcription reuse and explicit approved-profile changes
are implemented; automatic provider failover is not. A catalog entry alone is
not a working provider, and a local design preview is not a production result.

Latest user direction requests one-consent upload progression, stronger truthful
loading feedback, original AC/Dipak assets, customer-facing copy without model
configuration details, and partial guest report previews with account unlock.
These changes require the actual mounted UI and server projection to agree;
hidden report content must never be sent and merely obscured by CSS. API keys,
private call payloads and immutable operational receipts stay outside Git.
