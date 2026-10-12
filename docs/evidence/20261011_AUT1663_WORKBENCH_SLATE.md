# AUT-1663 — approved slate token and pulse contrast, shared dev

The coordinator approved the neutral `--lx-info` token on 11 Oct at 20:15 UTC, following the owner’s one-teal-accent rule. Implementation was already committed before this continuation: `a4ddad7a` (light `#56637a`, dark `#b7c2d3`, matching soft tints) and `64db3d05` (token assertions and learner embed mirror).

The continuation closes the interrupted dev readback. `fc769f2c` raises the calls library’s active-dot pulse minimum from 0.55 to 0.75. At 0.55 the slate dot reaches only 2.359:1 on a white surface; at 0.75 it stays above 3:1 on surface, paper, paper-2 and sunken in both themes. “Analysis in progress” / “Analysing”, “Report ready” / “Ready”, and “Needs attention” remain explicit labels. Status remains readable without colour or motion.

## Contrast

WCAG relative-luminance contrast; alpha `info-soft` is composited over the theme’s surface.

| `--lx-info` on |   Light |     Dark |
| -------------- | ------: | -------: |
| Surface        | 6.067:1 |  9.866:1 |
| Paper          | 5.611:1 | 10.997:1 |
| Paper-2        | 5.813:1 | 10.385:1 |
| Sunken         | 5.352:1 | 10.477:1 |
| Info soft      | 5.264:1 |  7.747:1 |

All exceed 4.5:1 for small text and 3:1 for solid chart marks. The focused token regression checks the actual pulse opacity against all four call-list surfaces in both themes; the old 0.55 fails it.

## Validation

- `pnpm exec vitest run app/lightbox/tokens.test.ts`: **17/17 pass**.
- The touched token test passes TypeScript with `--noEmit --incremental --target ES2022 --module ESNext --moduleResolution Bundler --lib ES2022,DOM --types node --skipLibCheck` and a seat-local build-info file.
- Cached ESLint for the touched test, Prettier for the changed files and scoped `git diff --check` pass.
- Post-commit browser sampling pauses the actual 1.4 s dot animation at 700 ms. At both widths the rendered minimum is 0.75, with **3.481:1 light / 6.053:1 dark** contrast against the actual row surface.

The first broad incremental typecheck and two combined browser waves were externally interrupted with exit 143; neither is claimed as a completed check. Their partial receipts remain. The first pulse sampler also counted the rep’s neutral avatar as a status dot; the corrected selector measures only children of the labelled status span. `slate-pulse/` preserves that rejected scanner result; `slate-pulse-final/` is the corrected readback.

## Dev evidence

Browser origin: `http://127.0.0.1:3026`, the existing shared hot-reload server. No build or extra dev server. Screenshot batches run through `ac-heavy`. Existing fictional journey data populates calls, dashboard and organisation; the native fictional `call-record.json` populates the preview’s talk split. The report uses the existing full-shell fictional fixture for standalone listen pins. The native Amit fixture merges its listen clip into an improvement, so it renders no standalone info pin; its captures are retained in `slate-moments/` and are not claimed as pin coverage. Browser API writes are refused. These receipts verify rendering of the committed token and retain source snapshots; they do not certify real account/API or production behaviour on a mutable workbench.

Screenshots and machine receipts are in `/home/acdev/strikes/1663/shots/2026-10-11/`:

- `slate-pulse-final/calls-{1440,390}-{light,dark}.png`: slate active dot alongside ready/attention labels.
- `slate-pulse-final/talk-split-{1440,390}-{light,dark}.png`: teal first voice, slate second voice, labelled shares.
- `slate-dashboard/dashboard-{1440,390}-{light,dark}.png`: call-status split and its named active series.
- `slate-organisation/organisation-{1440,390}-{light,dark}.png`: slate analysing call, teal report-ready calls and named attention state.
- `slate-listen-pins/moments-1440-light.png` and `slate-listen-pins-rest/moments-{1440-dark,390-light,390-dark}.png`: two native standalone slate listen pins (Must listen / Do this again), the same `--lx-info` family as Worth a listen.

All **16 scoped screen cases / 20 PNGs** are complete with HTTP 200, zero page errors, zero horizontal overflow and zero API writes. All selected captures were visually inspected. `slate-final-summary.json` composes successful cases from the bounded batches and records source snapshots, receipt hashes and all PNG hashes. Its SHA-256 is `49a0301b1a864aff1e53c2b8ca7a9046b5bd37076a1be03d90b47c4d11b4b46b`.

The listen fixture’s early clips cluster at the beginning of its long call, overlapping the old Details-map pins. The old call map also retains the already-reported blue/purple accents. These are B-owned legacy composition findings, not covered by this token repair or asserted as overall Report visual acceptance.

The incomplete combined wave is retained as `slate-readback/receipt.json`, alongside the partial pre-restart `slate-info/` captures. It is not represented as a complete matrix.

Shipping and production verification remain with the coordinator under workbench mode.
