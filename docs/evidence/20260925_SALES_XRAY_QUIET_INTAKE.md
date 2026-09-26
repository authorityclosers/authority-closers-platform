# Standalone intake declutter — 2026-09-25

The owner approved the cleaner staging report and asked that a fresh Sales Xray
user see a focused upload surface, not empty saved-call/activity tables and a
sample-insight/get-started sidebar. This change is one bounded part of Lightbox
P2; it is not the completed upload-continuity or v0.2 release.

## Implementation

- The real `AcquisitionStudio` route no longer mounts empty lower dashboard
  panels or the generic example rail for a standalone new call.
- A single recording uses one responsive column, capped at 960px; removing the
  rail does not leave an empty second grid column.
- Two or more actual selected files retain the existing queue guidance and
  file controls. Returning to one selected file restores the quiet layout.
- Embedded learner presentation remains unchanged. The Calls route, consent,
  account/profile/upload checks, advertised allowance and source upload contract
  are preserved.

## Validation

`vitest run app/acquisition-studio.test.tsx --maxWorkers=1` passed **73 tests**.
The added test mounts the real standalone page, checks the absent empty/example
panels, selects a file, and verifies that analysis remains disabled and no PUT
occurs before consent/checks. The existing multi-file continuation test now also
checks queue guidance for two files and its removal when one remains. Other
passing cases cover account gates, saved-call recovery, report and audio behavior.

Prettier was applied to the three changed source/test files. A loopback Next
preview was started for browser review, but Chrome navigation/focus commands
timed out under current host load. The owned preview was stopped. **Visual
verification remains pending**; no screenshot approval, staging deployment,
production deployment or new provider analysis is claimed by this receipt.

Upload continuity and its minimized indicator are covered by the companion
`20260925_SALES_XRAY_UPLOAD_CONTINUITY_P2.md` evidence note. Both slices were
validated together before this local commit; release and visual browser review
remain separate gates.
