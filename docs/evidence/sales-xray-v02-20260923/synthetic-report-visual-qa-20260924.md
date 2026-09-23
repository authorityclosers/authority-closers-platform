# Sales Xray synthetic report visual QA — 2026-09-24

## Preview and scope

- Local route: `http://salesxray.localhost:3016/review-fixture/report` (`aa720eb7`). It renders the production `ReportExplorer`, `SalesSkills`, and `NextCallPlan` components with invented dialogue for visual and interaction review.
- The fixture has no recording, account, analysis result, or provider call. Selecting **Listen** updates a visible source status; it does not play audio. This is not evidence of report content quality or an accepted coaching result.

## Browser observations

| Viewport | Observed result |
| --- | --- |
| 1440 × 900 | Document measured 1440 × 900. The preview frame stayed within x=40–1400; the initial Sales skills view had no horizontal or vertical scroll. Four skill cards and the source status were visible. |
| 1024 × 768 | Document content measured 1009 × 897 with a vertical scrollbar and no horizontal overflow. The skill reader compacted to two card columns; **Open notes** exposed the full observation and its exact source. The Next-call plan showed the explicit call outcome before the recommendation cards. |
| 390 × 844 | Document content width measured 375 with no horizontal page overflow. The Next-call plan height measured 1027 and the Sales skills height 864, with expected vertical scrolling. Cards stacked or compacted, and the skill notes opened as a bottom-sheet dialog. |

After the mobile review-sheet width fix (`f83b68ff`), a reload at 390 × 844 measured document client/scroll width 390/390 and dialog client/scroll width 390/390. The fixed dialog had no horizontal overflow.

The Sales skills tab's **Open notes: Human Connection & Trust** opened a dialog containing the synthetic quote “Understood. I won't schedule a follow-up.”, the exact `00:31.000–00:35.000` range, and source segment `synthetic-respect`. **Listen** closed the dialog and put that quote and range in the status region with “No audio exists in this display fixture.”

The **Next-call plan** tab displayed the exact outcome: “No sale was agreed. The buyer declined a next step and asked the seller not to follow up.” Selecting its `00:26.000` source updated the synthetic status with “I don't want to set another step today. Please don't follow up.” No next action was inferred. The browser exposed section tabs, a dialog, source buttons, and the live status region through semantic roles and labels.

## Verification and limit

- Fixture-focused tests: 2/2 passed. Typecheck, scoped ESLint, Prettier, and `git diff --check` passed for the fixture change.
- Mobile review-sheet follow-up: 4 focused files/40 tests, typecheck, and `git diff --check` passed for `f83b68ff`.
- These checks cover layout and source navigation for synthetic data. They do not validate a generated v5 report, audio playback, provider processing, or the coaching quality of a real report. The inspected v4 report remains below the requested quality bar pending generation and review of a v5 report.
