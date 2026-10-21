# Screenshot rubric (0 to 3)

The builder scores its own screenshots before asking for review. UI Guard scores the same set
again. Score what the pictures show, not what the code intends; if a criterion cannot be seen in
the set, ask for the missing shot instead of guessing.

## The screenshot set

For each changed screen, on the dev workbench with real data (see `SKILL.md`, "Check your work"):

1. 390 x 844 light, top of the screen.
2. 390 x 844 dark, same state.
3. 360 x 780 light (the narrowest common Android width), scrolled to the end.
4. 1440 x 900 light (computers), when the screen exists there.
5. Each overlay the change touches, open (the + sheet, a lead sheet, a hold menu, a picker).
6. The empty state and the loading outline, when the change touches them.

For the back rule, add a two-frame pair (overlay open, then after one back press) or a short
note of the check run in the harness.

## Score each criterion

0 = broken or missing. 1 = present but weak. 2 = good. 3 = could be shown to the owner as the
example.

| # | Criterion | 0 | 1 | 2 | 3 |
|---|---|---|---|---|---|
| 1 | **One primary action** | None, or two or more compete | One, but small, grey or out of reach | One, clear, in the lower half | One, unmistakable, thumb-reachable, label says the outcome ("Call Priya") |
| 2 | **Job first** | Top of the screen is chrome, greetings or settings | The job is there but below decoration | The top third answers why the user came | Seller sees the next action, owner sees the outcome, in one glance |
| 3 | **Fit and no overflow** | Sideways scroll, cut-off or overlapping content | Tight spots, a truncated key value | Fits at 360 and 390, nothing cut | Fits cleanly; inner panels scroll, the frame does not move |
| 4 | **Reach and touch** | Targets under 44 px, key action at the top only | Mostly fine, a few small or crowded targets | All targets 44 px or more, 8 px apart | Frequent actions sit in the bottom third; create is the + sheet |
| 5 | **Navigation and back** | Back leaves the app or the screen with an overlay open | Back works for some overlays only | Back closes every overlay shown, one per press | Plus a clear "where am I" (lit tab, title) and no dead ends |
| 6 | **Lists and rows** | Rows are walls of text, or tables on a phone | Readable but uneven; names in mixed case | Clear anatomy: name, one context line, status chip, time | Plus swipe actions with icon and label, and a hold menu as the alternative |
| 7 | **Controls and density** | Filter clutter, wide secondary buttons, stacked toggles | Some clutter or oversized controls | Stage tabs or a segmented control; compact chips | Every control earns its place; nothing to remove |
| 8 | **Words** | Jargon, internal IDs, raw enums, ALL CAPS labels | Mostly plain, a few technical words | Plain grade 8 to 10 words, sentence case, names capitalised | Labels say outcomes; numbers carry units; dates are relative ("Today 4:30 pm") |
| 9 | **States** | Blank screen, spinner only, red banner, raw error | A state exists but is generic ("No data") | Skeleton in the final layout; empty says how to start | Empty has one action; errors are corner cards that retry; no layout shift |
| 10 | **Numbers and charts** | Invented or unreadable numbers | Chart needs study to read | Takeaway title, readable values, 3:1 series contrast | Reads in two seconds; tap shows the exact value; trend chip where it helps |
| 11 | **Craft and consistency** | Off-kit components, raw colours, light and dark differ in layout | Mostly kit, some misaligned siblings | Kit components and tokens; siblings share structure | Vibrant, calm, aligned; looks designed on purpose in both themes |
| 12 | **House rules (gate)** | Any breach (see below) | — | — | No breach |

House-rule breaches (criterion 12 scores 0, and the screen is on hold whatever else it scores):
- a price, cost, minutes charged or "valid until" on a user screen;
- a customer or organisation name in UI copy, code, fixtures or file names;
- an emoji used as an icon or decoration;
- an app-level error as a banner or a full-page card instead of a corner card;
- invented numbers, waveforms, scores or trends;
- text under 4.5:1 contrast, or chart series under 3:1;
- a transcript ID, database ID or raw enum shown to the user.

## Decide

- **Pass**: criterion 12 is 3, no criterion is below 2, and the total is 28 or more out of 36.
- **Owner-ready**: pass, and 32 or more, with criteria 1, 2 and 3 at 3.
- **Hold**: anything else. Name at most three fixes, highest impact first, each tied to one
  criterion and one place on the screen.

When the builder and UI Guard differ by two or more points on a criterion, the reviewer explains
what it saw in the shot; the builder fixes or answers before the next round.

## Report template

```
Screen: Leads · build <sha> · shots: 390L 390D 360L 1440L sheet empty
Score: 30/36 · PASS (not owner-ready: criterion 2 is 2)
 1 Primary action      3  "Call next" bar above the tab bar
 2 Job first           2  Today list starts below the count strip; move it up
 3 Fit, no overflow    3
 4 Reach and touch     3
 5 Navigation, back    2  hold menu checked; stage sheet not shown
 6 Lists and rows      3
 7 Controls, density   2  "Export" is a wide outline button; make it an icon in More
 8 Words               3
 9 States              2  empty stage says "No leads"; say how to add one
10 Numbers, charts     2
11 Craft               3
12 House rules         3
Fix first: (1) empty stage text + Add lead action, (2) move Today list to the top,
(3) Export into the overflow menu.
```

Keep the report short. Point at the shot and the element; do not restate the rules.
