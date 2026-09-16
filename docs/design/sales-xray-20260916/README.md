# Sales Xray final-experience reference and acceptance map

Recorded 2026-09-16. Implementation baseline: `4c8cfe9e429d3712f988b90ae59e64159db58aa9`.
This is a **design/coverage handoff**, not a claim that all rows are complete.

## Approved visual direction and actual image outputs

The user's ten Sep16 00:13 desktop/mobile report references are the authority
for the visual direction: white, navy, mint/teal, blue, violet and orange;
rounded line icons; compact report navigation and focused evidence sheets.
Their illustrative numbers, scores and customer quotes are not application data.

Two additional genuine image-model references were generated in the user's
requested **normal ChatGPT6Pro chat**, not Work, an API call or an HTML render.
Both downloaded PNGs were inspected at full resolution on 2026-09-16. They are
reference assets only, not runtime overlays or browser QA screenshots.

| Output | SHA256 | Inspection |
| --- | --- | --- |
| [Paused desktop](processing-paused-desktop-v1.png) | `a6e8d9c77d7e02f4b40349029056f1a32cc0212d04ddf9f0480ee7d4b7545e3c` | Preserves palette; all recovery actions visible; no fake percentage |
| [Paused mobile](processing-paused-mobile-v1.png) | `ff13ece5aa83cfe67e2d25f9da1f45a0d9dff4ca9401eba675b1cecbb4d6ecee` | Complete portrait composition and bottom navigation; no clipped actions |

Desktop uses the user's `ChatGPT Image Sep 16, 2026, 12_13_13 AM (4).png`
as the uploaded style reference. Mobile derives from that and the generated
desktop. Original masters remain unchanged. Subscription cost is unknown.
Both are accepted as directional recovery references, not proof of exact CSS
dimensions. Functional one-viewport proof is in the separate compiled QA report.

Final prompt set: [prompts.md](prompts.md). Remaining report/edge-state image
references are **queued**, not generated. No new brand direction is proposed.

## Route and data seams

Public upload/report: `/` and `/?call=<authorized submission>` through
`StandaloneStudio`, `AcquisitionStudio`, `AcquisitionShell`. Calls: `/calls`.
Embedded learner flow uses `AcquisitionStudio` with `embedded`; it needs its
own integrated screenshot proof, not an inference from standalone snapshots.

Contracts are `report-contract.ts`, `overview-contract.ts`, acquisition-client
and the server-issued policy, session, submission/progress/report/evidence
responses. Historical or withheld fields stay absent. Assessment statuses
remain observed/insufficient_evidence/not_applicable/conflicted/unknown, never
invented Strong/Weak grades. Counts come from the supplied projection only.

All component paths below are under `apps/sales-xray-web/app/`. Synthetic browser
fixtures are `apps/sales-xray-web/tests/acquisition-fixture.ts`; production proof
is owned by the release coordinator and must be recorded separately.

## Acceptance matrix — current evidence versus required next pass

Every unfinished row requires desktop1440x900/1024x626 and mobile390x844/375x667
screenshots, keyboard/focus and reduced-motion checks, and contract-focused
tests. Normal composition fits one viewport; long text and detail live in
accessible focused panels/sheets rather than being clipped or made unreadable.

| Journey/state and real owner | Existing behavior/evidence | Required completion or gap |
| --- | --- | --- |
| Entry, selected audio, verification: `acquisition-studio.tsx` | New reference-style upload; consent and challenge preserved; 12 viewport checks | Live guest and signed-in learner proof; actual challenge still not automation-completed |
| Upload→C2→C4→C5→report: same component, `processing-visual.tsx` | Stable shell, real phases; 16 state checks +4 automatic transition checks | Provider-delay and reconnect image variants; real backend smoke separate |
| Paused recovery: same component | Saved work retained, explicit review before resume; four viewport checks; generated desktop/mobile refs | All server restriction reasons and consent/source rebinding regression |
| Saved calls: `calls-library.tsx` | Guest empty/sign-in state fits all four sizes; existing list tests | Signed-in long list, search/pagination, successful saved/reopened report screenshots |
| Overview metrics and Takeaway/Keep/Change/Outcome/Practice: `dipak-overview.tsx` | Existing factual metrics/cards and report tests; supplied mockups approved | Full responsive composition, empty/historical/preview/long copy proof; do not claim exact mock match yet |
| Every actual review point: `dipak-overview.tsx`, `review-dialog.tsx` | Source-backed map and previous/next dialog; actual priorities determine available points | Exercise every supplied point, absence/withholding, focus restoration and mobile sheet at all sizes |
| Source quotes/evidence: `finding-evidence.tsx`, `source-waveform.tsx` | Segment-bound quote/time callbacks; measured waveform, same-origin/no-store reads | Missing evidence and exact-source unavailable states; no synthetic waveform or precision in live UI |
| Moments: `report-transcript.tsx` | Transcript phrase search, speaker filter, pagination and source selection | Currently NOT the approved category-filtered moment list/detail layout; next/previous semantic moments and category mapping require actual report evidence |
| Sales skills: `report-factors.tsx` | Contract requires eight dimensions/status/observation, rendered in native disclosures | Mock's six-skill mapping does not exist; do not silently discard two dimensions or manufacture grades; mapping needs a controlled decision |
| Next-call plan: `next-call-plan.tsx` | First supplied improvement, overview focus/practice and source buttons | Keep/Change/Practice layout and real checklist interaction; no fake saved progress or invented strength fallback |
| Persistent audio: `call-audio-dock.tsx` | Actual audio, play/pause, seek, mute, rate and source waveform | Volume slider absent; unavailable/expired media and original-media coverage; no pretend playback |
| AudioAtlas/measurement evidence | `recording-measurements.tsx` / `measurement-contract.ts` exist in legacy `CallStudio`, not acquisition report | Map source-bound measurements and eligibility into the actual acquisition route; cursor is not playback-linked |
| Coach/material references | Citations and draft review status present in report contract | Eligibility/access and playable coach/material reference contracts not verified; no fabricated resource links |
| Upload errors, validation, cancel, retry | Existing acquisition tests and abort/source binding paths | Explicit image/state coverage for too large/unsupported/insufficient audio, user cancel, interrupted upload, safe retry |
| Provider/cost restrictions | Existing actual pause/quote controls | Simple copy per server reason; available, held and settled funds must stay distinct; no fake release/refund control |
| Session expiry, permissions and stale selector | Existing typed errors; timeout and guest401 regressions fixed | Complete expired/forbidden/deleted report and guest→account recovery screenshot proof |
| Offline/stale/reconnect and update notices | Polling/error handling exists | Dedicated offline, stale-read and application-update UX not yet verified; never label stale data as fresh |
| Successful report, saved/reopened and account claim | Synthetic upload reaches Overview at four sizes | Exact integrated production guest and learner proof; consent/ownership remain authoritative |
| Local-language and very long content | Existing transcript language/copy contracts | Mixed-script/long words, zoom, report-copy and missing evidence tests at target sizes; no semantic translation guesses |

Actual review-map families currently include supplied strengths and priorities,
golden moments, missed opportunities, prospect interpretations, rewatch,
conversation breakpoint, skills, next-call focus, practice, across-call pattern
and final assessment. Test the actual supplied set; do not hardcode a mock total.

### Independent contract inventory

A read-only follow-up review of this exact source tree found:

- The review map is 11 fixed entries plus up to three supplied priorities, not
  always14. Across-call progress is explicitly null in the current parser.
- The waveform renderer/parser exists, but this inspected source tree has no
  matching backend submission `/waveform` producer/route. The browser fixture
  returns404. Missing-waveform fallback was tested; end-to-end measured waveform
  delivery was **not** proved. Verify against the newer core release separately.
- AudioAtlas has a saved measurement contract and existing lazy component tests
  but is mounted only in legacy `CallStudio`, not `AcquisitionStudio`.
- The report dimension contract requires eight dimensions. The mock's six skill
  cards cannot become canonical categories by visual inference.
- Practice has instructions and a success condition, not a saved checklist,
  assessment or recording-launch contract. Any local checklist must say it is
  local and must not become official progress.
- Retained original audio has an owner-bound source endpoint; there is no
  original-media switcher/download/video UI in the acquisition report.
- Coach citations are `Doc-1`–`Doc-5` plus sections. They are not a resolved,
  authorized URL/excerpt/player contract. Do not invent those destinations.

These are acceptance gaps from the inspected baseline, not claims about newer
backend commits or new regressions caused by the upload slice.

## Release and safety boundaries

Ready upload/shell slice evidence:
[20260916_SALES_XRAY_UPLOAD_VIEWPORT.md](../../evidence/20260916_SALES_XRAY_UPLOAD_VIEWPORT.md).
The exact compiled tree passed206 frontend tests, lint, build,36 viewport checks,
four automatic transitions and four shell keyboard checks. This does not prove
the remaining rows or production deployment. Integration atop the live core
must preserve its backend fixes and re-run the candidate's checks.

DOCX/PDF redesign remains paused. Admin node settings/jobs-table work is next
after the public-flow slices; recordings API schema is owned separately during
the current release. No direct SQL, forced cost settlement, official AI score,
external private-call upload or fabricated media/progress is authorized here.

The workflow-ui-production skill shaped the state matrix, bounded implementation
and fixture-versus-live evidence. The imagegen prompting guidance shaped actual
raster references and inspection; execution used the user's explicitly requested
normal Pro chat instead of the skill's default built-in tool route.
