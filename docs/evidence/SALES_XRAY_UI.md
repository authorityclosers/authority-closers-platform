# Sales Xray standalone UI implementation evidence

2026-09-13. Owned paths: `apps/sales-xray-web/**`,
`packages/typescript/sales-xray-client/**`, and this evidence file.
No existing learner/admin/coach, authentication, navigation, migration or shared
design-system files were modified by this UI specialist.

## Implemented

- Separate Next 16.3.3 / React 19.2.8 conversation workspace named Dipak's Sales
  Xray. Uses AC's existing cobalt/academy colors, Clarity Grid spacing, supplied
  AC brand mark and editorial heading language. No remote font/media request.
- Workbench, transcript search/speaker filtering, literal evidence selection,
  segment occupancy map, source provenance, local session library and dual-lane
  review draft export. No simulated job progress or invented provider switch.
- Native AudioAtlas C1 checkpoint import with SHA-256-bound local audio playback.
  Source and decoded clocks, 40 ms/10 ms window/hop, display decimation and null
  gaps remain distinct. Original codec/container alignment remains uncertified.
  A C1-only import explicitly has no transcript or speaker attribution.
- JSON import is bounded to 5 MB; local audio preview is bounded to 100 MB.
  Imported files remain in browser memory; audio uses revocable object URLs.
  No upload, localStorage or sessionStorage write is implemented.
- Separate contextual/sales and measurements/attribution proposal lanes with
  Dipak and Suyash described as review owners. An exported local proposal has
  `reviewer_identity: null`, `submitted: false`, original revisions and evidence
  ID. Editing a proposal invalidates a prepared export. Draft text remains while
  navigating workbench/evidence/review for the current run.
- Acoustic-only C1 technical proposals require explicitly selecting a measurement
  series and exact point. Typed anchors preserve physical channel, decoded time,
  null/value, unit, measurement revision and window/hop/display stride. The source
  proof distinguishes a locally matched audio fingerprint from unverified
  checkpoint authorship/feature binary. No transcript or speaker is invented.
- Source weights remain 95 despite declared 100. Numeric publication is withheld.
- Thin standalone/LMS/free-course/website entry URL contract with exact origin
  allowlisting and the same run identifier. Presentation never selects a tenant.
- Same-origin AC API capabilities/example requests with response validation,
  visible service failures and retry. Saved-run links explicitly explain the
  missing authorized run connection rather than presenting the example as that run.
- Responsive light/dark appearance, keyboard labels/focus, skip link, reduced
  motion and literal Unicode text rendering.

## Test receipts

External receipt directory:
`D:/Projects/authority-closers-release-transfer/2026-09-13-sales-xray/receipts`.

- `client-tests.log`: 24 unit tests passed (native C1 clocks/nulls/source binding,
  malformed inputs, transcript identity/timing, Unicode literal text, exact entry
  origins and four presentation modes, immutable unsubmitted proposal lineage and
  rejecting different local contents under an already-open run revision, exact
  acoustic point anchors and missing/out-of-range point rejection).
- `ui-tests.log`: 5 component tests passed (literal rendering/XSS, unavailable
  API/retry, separate reviewer lanes, source weight discrepancy, no persistence).
- `ui-typecheck.log`, `ui-lint.log`: passed using bundled Node 24.19.0.
- `ui-build.log`: earlier optimized standalone Next build passed; compiled in 15.7
  seconds, TypeScript finished in 5.2 seconds. AC API proxy target was local
  `127.0.0.1:8016`. Final source changes were validated through the static build below;
  Node standalone runtime execution remains separately untested.
- `ui-static-preview-build.log`: current static preview export passed, compiled in
  4.8 seconds, TypeScript in 5.6 seconds. `AC_SALES_XRAY_STATIC_PREVIEW=1` selects
  static output for the existing loopback API server; the default remains
  standalone. Static mode omits Next rewrites/headers; the preview host owns them.
- `ui-static-preview-build-final.log`: final source including typed acoustic
  proposals passed compilation in 2.1 seconds and TypeScript in 6.9 seconds.
- `ui-actual-checkpoint-parse.json`: the supplied recording's actual C1 checkpoint
  passed the browser client's parser offline, with source binding retained,
  original/decoded 48 kHz, four series of 1,194 display points each, no transcript,
  and uncertified clock mapping retained. This check did not read media bytes or
  process anything externally.
- An initial Vite JSX transform failure was corrected using the current existing
  learner app's Vite 8 `oxc.jsx.runtime` configuration. The passing rerun is above.

Real browser/network testing is implemented in
`apps/sales-xray-web/tests/browser_network.py`. It generates only synthetic local
audio/checkpoints, calls the real AC ASGI example/capabilities routes, uses no
request interception or route mocks, checks local audio matching/rejection,
proposal export invalidation, responsive/keyboard behavior and network privacy,
and emits JSON plus screenshots. Final browser execution passed against the
same-origin static UI and actual AC ASGI API at `http://127.0.0.1:8016`:
`receipts/browser/browser-network.json`. Desktop/light, dark, mobile 390 px and
synthetic C1 and measurement-review screenshots were visually inspected. Nine checks covered the real
HTTP example/capabilities, transcript search/evidence, review export and
invalidation, the 95/100 discrepancy, source-matched local playback, wrong-source
and conflicting-revision rejection, exact C1 technical-proposal export with
source-proof flags, memory clearing, keyboard/reduced-motion and
mobile reflow. No page errors or external requests occurred; only same-origin GET
and blob requests were observed. No localStorage writes occurred.

The first run stopped on a test selector ambiguity between the application alert
and Next's empty route announcer; the actual conflict guard had worked. The test
selector was corrected and rerun successfully. The initial receipt is retained
as `receipts/browser/browser-network-attempt1.json`. The first passing baseline
is retained as `receipts/browser/browser-network-baseline.json`.

`receipts/browser/real-source-local-playback.json` records the supplied recording's
actual browser test: checkpoint import, four measurement series, exact original
audio fingerprint match, playback advancement, only blob requests after import,
no localStorage and local session clearing all passed in approximately 5.2 seconds.
`tests/browser_local_source.py` takes source paths as runtime arguments. It takes
no screenshots, emits no customer paths/content, uploads nothing and makes no paid
calls. This is local codec/source matching evidence, not provider, ASR or sales
quality evidence.

## Activation boundaries

This UI does not activate provider processing, account history, authenticated
review submission, private recording storage, minute grants, scoring or public
deployment. Those require the coordinator's shared AC contracts and capability
gates. Local library contents clear on refresh/close; they are not durable history.
Native C1 metadata is displayed as unverified imported review data; the browser
cannot establish its authorship or verify binary feature contents from JSON alone.

Starting the loopback frontend with both hidden `Start-Process` and tool-managed
foreground `next start` was rejected before execution by automatic command policy
with the sole stated reason `blocked by policy`. No launch succeeded through
those attempts. The coordinator mounted the static artifact in the existing
authorized local API as a supported preview. That preview does not constitute
testing of the Node standalone server runtime.
