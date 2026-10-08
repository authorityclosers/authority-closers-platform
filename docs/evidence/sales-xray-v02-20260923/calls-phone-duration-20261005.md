# AUT-1205: Calls phone duration

This is fictional browser-render evidence, not authenticated saved-call acceptance.
The existing sx-prospects preview serves this task on `http://127.0.0.1:3040`.
Implementation base: `ee5891e`; original failure pin: `b97e863` (PR #318).

The phone grid gave the status its intrinsic width and collapsed the duration
slot to zero. The scoped CSS now gives duration and status separate rows below
760px, preserving their text, controls, and desktop columns.

Run from `apps/sales-xray-web`:

```sh
node tests/browser_calls_card_layout.mjs
```

The fixture intercepts all `/v1/` requests, uses fictional IDs and report text,
and asserts that no write requests occur. It waits for loaded report text, closes
the guide, and checks text containment, unobscured hit targets, disjoint duration
and status rectangles, and absence of horizontal page overflow at 390 and 1440px.

| Render                     | Duration slot | Duration                    | Status                    | Result                                        |
| -------------------------- | ------------- | --------------------------- | ------------------------- | --------------------------------------------- |
| Original phone grid, 390px | 0px           | x151–237.23, y651.58–670.95 | x153–248, y650.08–672.47  | Duration obscured; regression assertion fails |
| Repaired phone grid, 390px | 100px         | x154.77–241, y622.45–641.83 | x146–241, y649.83–672.22  | Both exposed, 8px vertical gap                |
| Repaired desktop, 1440px   | 190px         | x878.77–965, y500.30–519.67 | x981–1076, y498.78–521.17 | Both exposed, 16px horizontal gap             |

The original-grid check changes only the rendered element's inline grid areas
in a scratch copy of the test; it does not restore or edit the shared checkout.
Phone and desktop screenshots were inspected. Selection, preview, rename, and
open-report controls remain visible. The Calls/drawer/insights/loading and owner
surface suites pass: 5 files, 53 tests. App lint, typecheck, and changed-file formatting
pass. Initial concurrent check processes were terminated; sequential retries
completed the checks.

Root owns authenticated acceptance on the dedicated fictional account. After
merge, open `https://salesxray-dev.authorityclosers.com/analysis/calls` and staging
at 390×844 with the existing saved fictional call: confirm duration and status
are legible without overlap, then check controls at 1440×1000. Do not create,
rename, or upload calls. AUT-1201 performs that check; it remains outstanding.
