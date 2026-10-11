# AUT-1677: Report continuation verified on shared dev

The Report keeps Dipak's six sections in order. This continuation fixes the
phone/tablet controls, aligns all eight Raw data skill rows with the Report,
preserves saved summary citations only for matching words, keeps assigned tasks
out of agreed commitments, and gives the folded speaker map the same seller
teal/prospect grey colours as the conversation timeline.

The binding source is
`/home/acdev/scratch/specs/final-xray-structure-2026-10-09.md`, SHA-256
`a464e69123f9a649f5f038e464d6086c6d52220b09e3e50eb24b44c6769e3110`.
The spec-to-component-to-field map is retained in
`/home/acdev/strikes/1677/NOTES.md`. This checkpoint reconciles completed local
checks and shared-dev receipts on 11 Oct; it does not represent a
new execution of those checks.

## Implementation

| Commit | Result visible on dev |
| --- | --- |
| `2eeeeb81` | Report navigation and return controls read the shared plain sales copy. |
| `6ebb0196` | Phone view controls are 44 px tall with a 6 px gap; tablet sections occupy their own row below the view controls. |
| `09a60321` | Matching saved summaries retain their evidence; unrelated pillar summaries borrow none. Prospect tasks stay separate from agreed commitments. Raw data uses current skill states and short names, with historical fallback. Speaker lanes and avatars agree; factual icons are neutral. |
| `a83151db` | The remaining Pushback map markers use the timeline teal. Playback and source refs remain unchanged. |

Saved report compatibility and missing-field gaps remain in the model. A
person's recorded outcome keeps its existing authority; these commits neither
create outcomes nor change access, scoring, providers or data.

## Focused checks

The retained `continuation-report-final/local-validation.json` records:

- Incremental Sales Xray TypeScript and changed-file cached ESLint: exit 0.
- Seven focused model/contract/screen/map/Raw data/corpus suites: 132 passed,
  72.14 seconds, beginning 22:55:58 UTC.
- Final colour follow-up: call-map contract suite 62 passed, 0.784 seconds,
  beginning 23:01:49 UTC. These overlap the prior checks and are not 62 new
  independent cases.
- Owned-path whitespace check: exit 0.

The corpus check reads retained reports locally and renders account and guest
projections. Real call content stays outside Git; no provider requests or
hosted writes are part of these checks. The validation JSON records completed
tool outputs and is not original JUnit.

## Shared-dev browser receipts

All paths below are under
`/home/acdev/strikes/1677/shots/2026-10-11/`.

| Receipt | Result | Source boundary | SHA-256 |
| --- | --- | --- | --- |
| `continuation-report-final/receipt.json` | 6/6, 1440/390/820 px, both themes, 22:59:21–23:00:52 UTC | `f380e35d` → `e981e16b` | `36c6a879bfa8b8a2b49e5949341083a5c2a18c4564197c1fe6c34baddb65df7d` |
| `continuation-map-palette/receipt.json` | 4/4, 1440/390 px, both themes, 23:08:36–23:09:08 UTC | `67992169` → `67992169` | `509eea75bed42fb6efd7f7d6af24a31726892523e6f6cdd09beb22de3f866abe` |

Both finite launchers exited 0. Every case has zero page errors, zero horizontal
overflow and zero outcome API requests. Shell API traffic is counted separately
and is not represented as zero requests. Fast Refresh events and mutable Git
boundaries remain in the receipts.

The functional matrix repeats the actual single interaction after a Deal
reload: open More views once, click Document once, then check its URL and all
six rendered Document sections. No forced click or retry substitutes for the
transition. It also checks phone tap height/gap, tablet separation, lane/avatar
colour agreement, neutral factual icons, and eight ordered Raw data skill rows.
The later palette matrix checks each Pushback marker against the theme's teal.

The earlier QA desktop/dark transition failure is retained at
`1694/shots/2026-10-11-workbench-team-clipping-readback/report-1440-dark.json`.
It recorded 14 Fast Refresh events and an assertion failure; the later six-case
single-click repeat passes. The original failure's cause is not established by
this repeat, and no permanent transition defect or proven refresh race is
claimed.

All affected screenshots were inspected in the implementation session. On this
checkpoint, these saved images were reviewed again:

- `continuation-map-palette/map-1440-light.png`: seller teal, prospect grey,
  neutral measurement icons and teal Pushback markers.
- `continuation-map-palette/map-390-dark.png`: readable folded speaker map and
  separated phone view controls above the bottom navigation.
- `continuation-report-final/story-820-light.png`: all six section labels fit
  on the separate tablet row below Report/Coaching.

The old intermediate captures remain retained. The final palette receipt
supersedes the earlier pink marker in functional-matrix map screenshots.

## Outcome evidence and delivery limits

[Executed compiled outcome evidence](20261011_AUT1355_RELEASE_OUTCOME_RECEIPTS.md)
supplies the formerly pending disposable API/PostgreSQL save → full reload →
Report/Document/Word criterion. Its exact-source passing execution and missing
sanitized outcome marker are both recorded; this checkpoint invents no marker.
That evidence is separate from the fixture UI checks above.

Shared-dev authenticated canonical save/reload and deployed staging/production
outcome acceptance remain **NOT RUN** by this seat. Mutable shared-dev receipts
are not immutable build-byte or shipped-version acceptance. The coordinator
owns release/version/staging/production operations.

Dev preview: `http://127.0.0.1:3026/review-fixture/report/story`.
Current Report continuation: **verified on dev; not shipped by this builder**.

## Guest-copy follow-up

G supplied the exact existing guest prompts in `defe554c`, with
[copy-module evidence](20261011_AUT1798_REPORT_GUEST_COPY.md).
`4e847e7c` makes the owned `report-sections/shared.tsx` import/re-export that
`GUEST` object and removes its duplicate declaration. The old and new object
declarations match byte-for-byte, including count, singular/plural agreement
and both account/sign-in labels. Existing callers keep the same export.

Incremental Sales Xray TypeScript, cached touched-file ESLint and owned-path
whitespace checks pass. The existing pillar-screen suite passes 8/8, including
hidden counts, singular/plural prompts, the original sign-in action and absence
of guest Coaching/Prospect buttons. The opt-in retained-report check passes 1/1:
13 saved reports, 13 account and 13 guest projections, 156 rendered pillars,
26 valid Word files, zero failures and zero provider calls. Three missing
baseline reports remain reported as missing. These are model/rendered reader
checks and do not claim a signed-out deployed persistence journey.

Actual Vitest JSON: `/home/acdev/strikes/1677/guest-copy-validation-20261011.json`.
Source/check pins: `/home/acdev/strikes/1677/guest-copy-source-pins-20261011.json`.
No new test assertions replace the original guest acceptance.

After the ordinary post-commit warm-up, the populated account-shell smoke
passes **4/4**, 1440/390 px in both themes, 23:23:03–23:23:15 UTC. All four
cases have zero page errors, sideways overflow and outcome requests. Existing
shell API traffic is eight requests per case, retained without a zero-traffic
claim. Phone Report/Coaching controls remain 44 px with a 6 px gap. All four
saved screenshots were visually inspected; the finite launcher exited 0.

Receipt/screenshots:
`/home/acdev/strikes/1677/shots/2026-10-11/guest-copy-shared/`.
`receipt.json` SHA-256:
`ec75bdbb1b6e71125fe161cefa54c10b3e59518ea51616a3e112e60e49233afd`.
Sampled source HEAD stayed `84b2c876` during the smoke; `source-pins.json`
records unchanged owned copy/reader bytes and all four screenshot hashes.
The smoke exercises the account shell. Guest hidden-count/sign-in agreement
comes from the separate original rendered test and offline projections above.

| Input | SHA-256 |
| --- | --- |
| Actual focused Vitest JSON | `c1b12fa5924a37ef6d49044fafe1fae43f1e8f902a92aa7bcc1231dd17eb9675` |
| G's committed `report-copy.ts` | `549ab86125297423c59a2053c61012bc170ea9db42571205205cd5060d817f63` |
| B's committed `report-sections/shared.tsx` | `befb261c50f0b6012c46e16c197c7a3e0a0f1eb09409bc9f0c1855e4b9e90b41` |

All owned implementation files are committed, and no unblocked source item
remains in this Report continuation. Independent deployed persistence,
future v8 admission and release/production completion keep their existing
owners; this evidence closes no such criterion.
