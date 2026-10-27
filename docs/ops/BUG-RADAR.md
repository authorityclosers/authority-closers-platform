# Bug radar: the UI bugs the owner finds by hand, found by machines on every build

The orchestrator for the owner, 26 Oct 2026: the owner kept finding Sales X-Ray UI bugs from his own phone. Examples:
- the Leads list past the right edge (#28);
- the Review pill over a title;
- cards centred, wasting a phone's width;
- the Leads setup tabs not switching;
- Now / All leads / More cut at 320 px with 130% text.

He wants bug spotting 100–200 times faster. The radar checks every screen state on every build; people and telemetry
(`telemetry/friction.py`, the bug reporter) cover the real-world rest.

## What it checks

Every review fixture (fictional data, no API, no credentials) is checked:
- every named matrix screen in `scripts/ci/wb_matrix_lib.mjs`, and every other `app/review-fixture/**/page.tsx`;
- at 320x640, 360x800, 390x844 and 1280x800;
- at 100% and 130% text, plus the Android app's 130% zoom on phones;
- in light and dark.

That is 22 states a page. In each state the page is measured (`radarScan` in `scripts/ci/wb_radar_lib.mjs`):

| check | finds | severity |
|---|---|---|
| `overflow-element`, `overflow-page` | an element past the screen's edge (outside a scroller), or the page scrolling sideways | high on a phone |
| `overlap` | text lines and controls drawn over each other in one layer (the page, a fixed or sticky bar, a dialog) and one scroller: a pill over a title | high with a control, else medium |
| `clipped-label`, `clipped-text` | a tab, button, chip or heading cut by an ellipsis, a clip or a line clamp; long data text is `clipped-text` | high when under 60% shows |
| `text-spill` | text running visibly out of its control | medium |
| `tap-target` | a control under 44 x 44 px on a phone (inline links in a sentence are exempt; a widening `::before`/`::after` counts) | medium under 24 px, else low |
| `contrast` | text under 4.5:1 (3:1 for large text) against its own and its parents' backgrounds | high under 2:1, medium under 3:1 |
| `centred-card` | a card on a phone with over a quarter of the width empty, split on both sides | medium (low in a dialog) |
| `console-error`, `page-error`, `request-failed` | console errors, uncaught errors, failed same-origin requests while loading | medium; uncaught and hydration errors high |

Then every safe control is tapped once, at 390 px (and at 1280 px for computer screens). Nothing labelled Delete,
Remove, Log out, Send, Call, WhatsApp, Pay or Upgrade is tapped, and nothing that leaves the app (tel:, mail,
another site, a new window). A list's rows get one or two taps; every tab gets one. While a modal sheet is open,
only its own controls are tapped.

| check | finds |
|---|---|
| `dead-tap` | nothing changed in the page, the address, scroll, focus or checkboxes within 1 s |
| `tab-no-switch` | a tab that does not light up, or lights up while the content below stays the same (high for real tabs; low for a segmented switch, which may only set a mode) |
| `tap-blocked` | something drawn over the control takes the tap |
| `tap-error` | a console error, an uncaught error or a failed request after the tap |
| `sheet-offscreen` | a sheet or dialog opened by the tap reaches past the screen's edge, or below it without scrolling |

A sheet a tap opens is measured with the static checks too.

Each finding has a stable key: check, page and element path. The path is the element and up to three meaningful
ancestors; CSS-module hashes, generated ids and positions are dropped. The same key at several widths, scales and
themes is one finding, listed with where it shows. Findings are grouped by root cause:
- the same component on any page;
- faint text by its colour pair (one design token);
- errors by their message.

Groups are ranked by severity, then the number of pages, then the number of states.

## Running it

```bash
ssh ac wb-ci --radar                        # every page, 5 shards on GitHub (~15 min); artifact wb-radar
ssh ac wb-ci --radar hub-reviewer leads-all # some screens (names from wb_matrix_lib.mjs, or fixture paths)
ssh ac wb-ci --full --radar --sha <sha>     # the radar alone for a commit (what the nightly and a hold run)
sudo ac-bug-radar check --sha <sha>         # a release hold: groups the nightly baseline doesn't know
```

- The artifact `wb-radar` (kept a day) holds `report.md` (also the run summary), `radar.json`, `crops/<finding>.jpg`
  and `pages/<screen>.jpg` (each screen whole, at 390 px, 100%, light). The shards' parts are folded into it and
  deleted, so a run leaves one artifact (the workbench storage policy).
- Findings never fail the job. A shard fails only when over a quarter of its pages never loaded.
- To debug against a fixture server you already run:
  `WB_RADAR_ORIGIN=http://127.0.0.1:3000 WB_RADAR_WORKERS=1 node scripts/ci/wb_radar.mjs run out .wb-ci/request.json`,
  then `node scripts/ci/wb_radar.mjs merge out`.

## Every night, and the cards

`ac-bug-radar.timer` runs `/usr/local/sbin/ac-bug-radar nightly` on ac at 22:30 UTC (04:00 IST), for development only:
1. It waits while a release cut or ship runs (`ac-ship`, `/var/log/ac-ship.log`; cuts hold wb-ci slots 2–6).
2. It runs `wb-ci --full --radar` for the workbench head (the code dev serves) on GitHub, never on ac.
3. It downloads the report to `/var/lib/ac-bug-radar/runs/<when>/` (kept 14 days).
4. It keeps the cards in AC Pulse under "Bug radar", which sits under "Revenue: AC features in AC Pulse HQ":
   - each group has the marker `radar:<group id>`;
   - a new group of medium or high severity becomes a card, at most 10 a night (the rest wait, listed on the parent);
   - a group that is gone while all its pages were checked marks its card done; one that comes back reopens it;
   - low groups are recorded in the report, without a card.

Cards carry:
- the check, the component and the pages;
- the numbers, an example and the dev fixture link;
- the crop and report paths on ac.

They never carry a name (two capitalised words become "[name]"), an amount or report text. Production `bug_reports`
are untouched: the radar is not a person reporting.

- The first run: `sudo ac-bug-radar baseline --cards 15`. It records every group and cards only the 15 to fix first.
  The rest are known debt, listed in the report.
- Give a known group a card later: `sudo ac-bug-radar card <group id>`.
- State: `/var/lib/ac-bug-radar/state.json`.

## The speed check (slow phones)

The orchestrator for the owner, 27 Oct 2026: "on low-end devices with the worst processors this app might be slow".
Telemetry can't name the low-end phones yet: Chrome caps memory at 8 GB and budget phones have 8 cores, so every phone
reports tier "high". So the speed check times the screens in a lab instead.

What it does:
- **Build:** a production build of Sales X-Ray made with `AC_SALES_XRAY_PERF_FIXTURES=1`. Only that build has
  `app/perf-fixture/[screen]/page.perf.tsx` (next.config.ts `pageExtensions`). It shows the review fixtures' fictional
  screens with production React; every other build, deployments included, leaves the file out.
- **Screens:** Home; Leads (All, My work, board); Calls; the Report; Chats; the organisation; Settings.
- **CPU:** 1x, 4x (about a mid-range phone, Lighthouse's mobile setting) and 6x (a low-end phone), through Chromium's
  CPU throttling. The phone is 390 px.
- **Runs:** three of each, one at a time, so nothing shares the CPU. The median counts.
- **What is timed, as telemetry times real phones:**
  - opening the screen: until it is ready to use (settled, and the main thread free for 500 ms, since hydration runs
    as long tasks while the page looks done), with LCP and blocking time;
  - each tap telemetry names (open a lead, switch a tab, open a sheet), on a ready screen: from the tap to settled
    (150 ms quiet after the page first answers). A tap that does a full page load instead is listed as "left".
- **Slow at 6x:** a screen over 3 s or a tap over 1 s. "For the builder": over 5 s and 2 s.

```bash
ssh ac wb-ci --speed                  # every screen; artifact wb-speed (report.md, speed.json)
ssh ac wb-ci --speed leads report     # some screens
```

The nightly `ac-bug-radar` run carries it (`wb-ci --full --radar --speed`):
- What is slow keeps a card, marker `perf:<screen>:<action>`, under "Speed check: Sales X-Ray on slow phones, every
  night". Its title says "for the builder" over the builder's limit.
- A card closes when a later night measures it fast enough, and reopens if it slows again.
- Reports: `/var/lib/ac-bug-radar/runs/<when>/speed/`.

## The optional AI review

`ac-bug-radar nightly --ai N` (or `AC_BUG_RADAR_AI_PAGES=N` in the unit's environment) is off unless asked. It is
the last step:
1. It looks at N screens' whole-page shots with the `sales-xray-ux` rubric, through the Claude subscription
   (`claude -p --model sonnet` as acdev, never an API key).
2. It runs only while the usage guard's gate is open (`/var/lib/ac-usage-guard/strike-gate.json`, `claude_ok`).
3. The prompt asks for findings only, at most 5 a screen, and only what the machine checks miss.
4. Findings go to the report and one comment on the parent card, never to cards of their own.
5. The screens rotate night by night.

## What the checks cannot tell

- Fixtures have no API. A tap that would call one fails here without being a bug (`tap-error`, `request-failed` on
  `/v1`, low).
- Faint text uses the element's own and its parents' backgrounds. Text over a picture, a gradient or a frosted bar is
  skipped. Text over a sibling (an absolute badge) may read wrong.
- One or two letters (a monogram, a brand mark) are listed as low.
- A badge placed over its own icon on purpose shows as an overlap when the two are siblings.
- A small icon inside a big tappable row is still a small target (low).
- A copy button with no toast is a dead tap, on purpose: it gives no feedback.
- A centred alert dialog is a low `centred-card`.
- A days-of-the-week multi-choice (several pressed) is not treated as tabs; a segmented switch with one pressed is.
- Hidden content counts as hidden when Chrome says so (`checkVisibility`): a closed `<details>` menu has boxes but
  is never painted. The first baseline listed 42 such menus as overlaps before this.
- Overlaps are compared inside one scroller, so content scrolled under a sheet's footer is not an overlap.
- A crawl's first tap on a fixture can wait for `next dev` to compile a lazy chunk; a page that fails to open is
  tried once more.

## Device coverage beyond fixtures (proposed, not set up)

See side notes `bug-radar-20261026/device-coverage.md`: Firebase Test Lab Robo on the Android app, and the Play
pre-launch report.
