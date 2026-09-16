# Sales Xray — native top-layer report readers

Follow-up to `b06c87ab3d506149281171b774ba44ef1b792a74`, 2026-09-16.

## Actual production defect

Read-only inspection of the user's already-authorized 20:53 report in Chrome
confirmed the reported clipping at 1536×674. The `.studio-report.panel` entrance
animation (`appear`, forwards fill) retained an identity transform. That made
the formerly fixed dialog backdrop relative to the report, not the viewport.
With `.studio-main.scrollTop=523.2`, the backdrop top was -448.8 and the dialog
top -31.3. Other scroll positions pushed almost the entire dialog off screen.
Earlier reduced-motion fixture runs disabled this transform and missed the bug.
No production call content, credentials or session material is saved here.

## Correction

Shared Overview/Skills/Plan readers now use native `dialog.showModal()` top-layer
modality. In-place DOM ancestry preserves report styles; top-layer positioning
escapes transformed and scrolling ancestors. Existing focus restoration,
Escape/cancel handling, source actions and unbounded print remain. No backend,
parser, upload, quote or authorization change.

## Verification

- Next production build and TypeScript passed.
- Full frontend suite: 238/238 passed with `vitest run --maxWorkers=2`.
  A concurrent full-worker run during the build hit two 5-second test timeouts;
  limiting worker contention passed without changing test thresholds.
- Independent read-only review: 27/27 focused tests; no new P0–P2. Reviewer also
  compared native/nonmodal Chromium print output (both six pages).
- Compiled candidate at loopback3116, Chromium, **normal motion**. Five sizes:
  1536×674, 1440×900, 1024×626, 390×844, 375×667. **105 result records passed**.
- **20 top-layer assertions** across Moments, Skills, Plan and Overview verify
  `:modal`, actual identity-transformed report ancestry, and unchanged sheet
  rectangles after forcing the actual shell to scroll400px. Every header/footer
  remains inside the viewport. All report tabs, card/page navigation, twelve
  fixture review points, focus restoration and print checks pass.
- Desktop1536 Skills/Overview and phone375 review screenshots visually inspected.
  [Measured data](sales-xray-top-layer-20260916/results.json) and screenshots are
  in the same directory.

## Remaining live gate

The local production-data bridge was restarted through its pinned-origin code.
Normal Google sign-in requires the user's passkey; no cookies were extracted,
session transferred or verification bypassed. Thus **actual production baseline
diagnosis is verified; actual private-call candidate verification is pending**.
The release coordinator will merge this correction with the strict recovery
envelope/quote fix and verify the promoted artifact using the already-authorized
production report. This document is not a live-release or real-audio E2E claim.

Reference ZIP extraction stays local under `.tmp/sales-xray-user-refs-20260916`;
20 supplied images contain14 unique hashes. Separate page-by-page design audit
owns further icon/transcript control polish, not this positioning correction.
