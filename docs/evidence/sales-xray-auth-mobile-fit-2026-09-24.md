# Sales Xray mobile auth fit — 2026-09-24

Scope: presentation-only change to `apps/sales-xray-web/app/account-auth.module.css`, based on `7135edf7bba620cd7343315895d0524fb7d7facd`. No auth, consent, file, or provider behavior changed.

The mobile hero now uses a 72 px branded strip with the existing wordmark and animated waveform. The form keeps its Terms and Privacy links, 46 px email input, 47 px primary button, local-file status, retention note, and existing-password action. The decorative hero headline is hidden at mobile widths; the form's H1 remains visible.

## Browser geometry

Measured in the synthetic `auth.email` fixture through the local read-only bridge (`http://salesxray.localhost:3018/?new=1&sx-fixture=auth.email`). The fixture has a local metadata-only selected file and sends no account or provider request. Screenshots were captured in the Codex task at both target sizes.

| Viewport | Before document height | After document height | Terms bottom | Primary action bottom | Local-file status bottom | Existing-password action bottom |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 360 × 800 | 1015 px | 800 px | 477 px | 565 px | 624 px | 707 px |
| 390 × 844 | 966 px | 844 px | 462 px | 550 px | 609 px | 692 px |

Both target screens have no horizontal or vertical document overflow in the initial selected-file state. A 1536 × 674 desktop check remained at 1536 × 674 document size, with the alternate action ending at 666 px. At 320 × 600, the document grows to 785 px with visible overflow so keyboard, zoom, or longer error states remain scrollable.

## Checks

- Node 24.19.0: focused Vitest suite, 3 files and 18 tests passed (`account-auth`, `login/page`, `sales-xray-fixture-preview`).
- Node 24.19.0: TypeScript `tsc --noEmit` passed.
- App ESLint `--max-warnings 0` passed.
- `git diff --check` passed.

Screenshots and geometry are from the private local fixture. No production API write, sign-in, upload, analysis, or provider call was performed.
