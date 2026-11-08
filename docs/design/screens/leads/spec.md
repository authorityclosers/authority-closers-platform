# Leads, first viewport: build spec (L1R, chosen 8 Nov 2026)

**Status: chosen. The owner picked L1 on 8 Nov 2026 ("Build L1").** Build this. Three independent judges (a high-volume
seller, the owner and coach, an Apple/CRED-level visual designer) ranked round-1 direction L1 first of six (31, 31, 29 of 36;
looks 8, 8, 8; all "above" today's Leads, style match with Dipak's Home "strong"). L1R is L1 with their fixes.

The images in this folder are the design source. Take the look (order, proportions, colour, type relationships) from the
images; take sizes from this spec. Images are references, never proof: the build is accepted on real screenshots at the
acceptance sizes next to these images.

| File | What | Source run |
|---|---|---|
| `l1r-to-call-light.webp` | To call view, light, 363 × 735 | `leads/20261108-W7-v01` (refined from `leads/20261108-W4-v01`) |
| `l1r-to-call-dark.webp` | The dark pair | `leads/20261108-W7-v02` |
| `l1r-follow-ups-light.webp` | Follow-ups view with day sections (borrowed from L6) | `leads/20261108-W7-v03` |

Floor: today's Leads (dev review fixture, 8 Nov, 363 × 735) and production v1.37 Leads. Style: Dipak's Home as built on dev
(commit 6b14a9c0f): its app bar, `SideSelector tone="calm"`, card, chip and `CallLens`. Leads reuses those components; it does
not restyle them.

## 1. How to read the image

The image model draws everything at about 80 % of true size. Measured on `l1r-to-call-light.webp` (882 × 1783 px, 2.43 px/dp,
the measured boxes are in `measure-boxes.json` in this folder, in image pixels), against Home as built:

| Element | Measured in the image | Build (true size) | From |
|---|---|---|---|
| Side gutter | 9–11 dp | 16 dp | Home |
| Inbound \| Cold control | 35 dp | 48 dp (44 option + 2 + 2) | `side-selector.module.css` calm |
| View tabs row | 21 dp text block, underline 82 × 3 | 44 dp row, 3 dp underline | this spec |
| Stage chip | 23 dp | 32 dp | this spec |
| Filter button | 30 dp circle | 40 dp circle in a 48 dp touch box | this spec |
| Row avatar | 34 dp | 40 dp | this spec |
| Row Call / WhatsApp circle | 35 dp, centres 43 dp apart | 44 dp, centres 52 dp apart (as today's Leads) | judges (all three) |
| Row name | ≈ 14 px | `--sx-text-md` (16.5 px on phones), 500 | Home type scale |
| Row lines 2–3 | ≈ 13 px | `--sx-text-xs` (13 px on phones), 400 | Home type scale |
| Call capsule | 38 dp | 56 dp | `call-lens.module.css` |
| App bar / tab bar | 54 / 51 dp | 64 / 63 dp | Home fixture, measured at 3× |

Colours measured (snapped), with the token to use:

| Element | Measured | Token |
|---|---|---|
| Page | #F0F0F8 | `--sx-paper` |
| Control well / thumb / unselected label | #E0E4E8 / #FFFFFF / #58606C (5.0:1) | `--sx-fill` / `--sx-elevated` / `--sx-muted` |
| Selected tab text / unselected | #000 / #505864 (6.3:1) | `--sx-ink` / `--sx-muted` |
| Tab underline | #005848 | `--sx-accent` |
| Selected chip fill and ink | #D8F0EC, deep teal | Home's `.chip[data-tone="good"]` mix |
| Unselected chip | white, ink #505868 (7.2:1) | `--sx-surface`, 1 px `--sx-line`, `--sx-ink-2` |
| Row name / lines 2–3 | #000 / #505868 (7.2:1) | `--sx-ink` / `--sx-muted` |
| Late line | #B80000 (6.9:1) | `--sx-bad` |
| Row circle ring | #B0B4C0 | `--sx-line-strong` |
| Call capsule | #005C54 under white, 7.9:1 | `--sx-call-fill` / `--sx-call-ink` (#045d56 / #fff light; #2dd4bf / #0b0c0e dark) |

## 2. Layout at 363 × 735 (the owner's OnePlus), true size

| y (dp) | Element | Height | Notes |
|---|---|---|---|
| 0–64 | App bar | 64 | Home's, title "Leads". Search stays the app bar's search icon (one tap). |
| 76–124 | Inbound Leads \| Cold Leads | 48 | `SideSelector tone="calm"`, full width inside 16 dp gutters, 12 dp under the app bar. |
| 128–172 | View tabs | 44 | One line, never wraps. Hairline `--sx-hairline` under the row, inside the gutters. |
| 180–212 | Stage chips + Filter | 32 | 8 dp under the tabs. |
| 224–600 | List card | 376 viewport | 12 dp under the chips. Scrolls; only the tabs and chip row pin on scroll (L1). |
| 600–672 | Call band | 56 + 8 + 8 | `CallLens` "Call next lead · 128", on the page colour, 8 dp above and below. The list ends above it: no row is ever covered. |
| 672–735 | Tab bar | 63 | Home's, Leads active. |

Controls above the list: 160 dp under the app bar (today: about 336 dp from the app bar's bottom to the first row, measured the same way by two judges).

## 3. Components

**View tabs.** Three text tabs, left-aligned, each hugging its text, 24 dp apart: "To call 128", "Follow-ups 12", "All leads 387".
Label `--sx-text-sm` (15 px phone): selected 500 `--sx-ink`, unselected 400 `--sx-muted`; the count follows the label after one
space in 400 `--sx-muted`, tabular figures, the same style on every tab (#167). Selected underline: 3 dp `--sx-accent`, the
width of the tab's text, top corners rounded 3 dp, on the row's hairline. Counts count the selected side (#166). If the three do
not fit (130 % text, 4-digit counts), the row scrolls sideways; it never wraps (#165, #180) and never truncates.

**Stage chips.** One row, 32 dp chips, radius 8, padding 0 12, 8 dp apart, label `--sx-text-xs` (13 px). Selected chip: Home's
"good" chip colours, a 16 dp check before the label, 500. Unselected: `--sx-surface`, 1 px `--sx-line`, 400 `--sx-ink-2`.
**Counts follow the selected view and add up to the tab's count** (judges' honest-numbers fix): with To call 128, "All stages
128", "New lead 46", "Not connected 38", "Open leads 26", "Interested 12", "Meeting scheduled 6" (fictional split). Chips size to
their text and never wrap; the row scrolls sideways and fades (24 dp, page colour) under the Filter button. Stages with 0 in the
selected view: hidden (open for the owner).

**Filter button.** Pinned at the chip row's right end: 40 dp circle, `--sx-surface`, 1 px `--sx-line`, 20 dp sliders glyph in
`--sx-ink`, 48 dp touch box. It opens the existing `FilterSheet`; the sort pick moves inside it. With search in the app bar, that
makes two filter entry points, not three (#171, Dipak's "3 → 2"). A dot on the button when a filter other than stage is on.

**List card.** Home's card: `--sx-surface`, 1 px `--sx-line`, radius `--sx-radius-lg`, inset 16 dp; rows separated by
`--sx-hairline` across the card's width.

**Row.** Minimum 72 dp; padding 10 dp top and bottom, 12 dp sides.
- Avatar: 40 dp initials circle, as in the image (grey fill, white initials 500).
- Text column, 12 dp after the avatar:
  - name `--sx-text-md` 500 `--sx-ink`, line height 22, wraps (never "…"; at most 3 lines);
  - line 2: an 8 dp stage-colour dot (`stage-look.ts`), 6 dp gap, the stage word in `--sx-ink-2`, then " · " and the source in `--sx-muted`;
  - line 3: the next step in `--sx-muted`, starting under the stage word.
  - Lines 2 and 3 are `--sx-text-xs`, line height 18.
- Late: line 3 reads "Late · was due 2:00 pm" in `--sx-bad`, with "Late" in 500. The word carries it, not only the colour.
- Actions: Call, then WhatsApp, as 44 dp neutral outline circles (1 px `--sx-line-strong`, 22 dp glyph in `--sx-ink`). Centres are 52 dp apart, each a 48 dp touch box, vertically centred, 12 dp from the card edge.
- Tapping the row opens the lead, as today.

**Call band.** `CallLens` as on Home: full width inside the gutters, 56 dp, label "Call next lead · 128" (Follow-ups: "Call next
follow-up · 12"). The one primary action on the screen; nothing else is deep teal except the tab underline and the selected chip
tint.

**Follow-ups view** (`l1r-follow-ups-light.webp`; the image wraps "Meeting scheduled 2" and cuts Due today after one row: the rules here win). The same screen, with the list grouped by day: one card per group
(Overdue 3, Due today 6, Upcoming 3). Each card has a header row inside it: the label in `--sx-text-sm` 500 `--sx-ink`, the count in
`--sx-muted`. Headers are never red; only the "Late · was due …" lines are. Group counts and chip counts add up to the tab's 12. A
group longer than 5 rows ends with "Show all N".

## 4. True-size row budget (read this before promising rows)

At true size the image's row (avatar + text + two 44 dp circles) leaves a **151 dp text column** at 363 dp
(363 − 2 × 16 gutters − 2 × 12 padding − 40 avatar − 12 gap − 96 actions − 8 gap). The fixture names are deliberately long:
"Venkatesh Subramanian Iyer", "Priyadarshini Kulkarni-Deshpande" and "Mohammed Faizan Shaikh" all wrap to two lines at
16.5 px, and "New lead · Meta lead form" wraps at 13 px. Built honestly, 363 × 735 shows **about 3 rows of these long-name
leads** and about 4 rows of typical names, not the image's 5. Today's Leads shows 2.5 truncated rows.

Open for the owner, one choice:
- **A. Drop the initials avatar.** The text column becomes 203 dp; most names fit on one line, line 2 fits, and 363 shows
  about **4 rows even of long names**. The stage dot leads each row instead. This is my recommendation as designer; it changes
  the picture, so it needs his yes.
- **B. Keep the avatar as drawn.** About 3 rows of long names, 4 of typical ones.

**Build B (as drawn) until the owner says otherwise:** he picked the image with the avatar. A is a later, separate choice.

## 5. Other acceptance sizes and states

| Size / state | Behaviour |
|---|---|
| 360 × 800 (Vivo) | Same layout; the list viewport grows by 65 dp: about 4 rows of long names (B), 5 (A). |
| 390 × 844 | Text column 178 dp (B) / 230 dp (A); about 5 rows. |
| 1440 × 900 | Today's desktop frame stays. The list column gets the same stack (Inbound \| Cold, tabs, chip row, rows). At this width all chips fit without scrolling, and the Filter button sits at the row's end. A 1440 image is rendered once the owner picks. |
| 130 % / 200 % text | Tabs and chips scroll sideways and never wrap. Names wrap to 3 lines. The Call label wraps to its own line (v1.38 rule). At 200 %, at least 1 whole row shows (L1). |
| Dark | Home's dark tokens. The Call is `#2dd4bf` with a near-black label. Red only on "Late …". Image: `l1r-to-call-dark.webp`. |
| Cold side | Same screen. All counts are Cold's. |
| Empty view | One line in the card ("No leads to call. New leads appear here.") and no Call band. |
| Loading | Home's skeleton pattern: the tabs and chips draw at once, rows as grey bars. The cached first paint shows a "syncing" sign (#67). |
| Long numbers | Counts up to 4 digits on tabs and chips; 3-digit counts in the fixtures (128, 387). |

## 6. Asks covered

| Ask | How |
|---|---|
| Dipak: stages visible | The stage chip row, with counts that follow the view. |
| Dipak: three filter rows → two | Tabs and chip row. Sort moves into the Filter sheet, so there is no separate sort row and no full-width "All stages" row. |
| Dipak: Inbound \| Cold like Home | Home's own `SideSelector tone="calm"`, not a copy. |
| #165, #180, #169 | Tabs on one line with trailing counts; they scroll instead of wrapping. |
| #167 | One count style on every tab; no truncated stage select. |
| #171 | Two entry points: search (app bar) and Filter (chip row end). |
| #88 | Six control rows become three (control, tabs, chips); controls take 160 dp instead of about 336 dp. |
| #166 | Counts count the selected side (data fix; the design shows per-side counts). |
| #67 | Cached first paint with a syncing sign (Loading state above). |
