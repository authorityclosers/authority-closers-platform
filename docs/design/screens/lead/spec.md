# Lead page (Prospect's Information), first viewport: build spec (P5R, chosen 8 Nov 2026)

**Status: chosen. The owner picked P5 on 8 Nov 2026 ("Build P5").** Build this. Three independent judges (a high-volume
seller, the owner and coach, and an Apple/CRED-level visual designer) each ranked round-1 direction P5, "Story timeline", first
of six. It scored 29, 29 and 29 of 36, looks 8, 8 and 7.5, and all three placed it above today's lead page. P5R is P5 with their
fixes.

The images in this folder are the design source. Take the look (order, proportions, colour, type relationships) from the
images; take sizes from this spec. Images are references, never proof: the build is accepted on real screenshots at the
acceptance sizes, next to these images.

| File | What | Source run |
|---|---|---|
| `p5r-light.webp` | First viewport, light, 363 × 735 | `lead/20261108-W7-v01` (refined from `lead/20261108-W4-v05`) |
| `p5r-dark.webp` | The dark pair | `lead/20261108-W7-v02` |

**Overrides of the image** (the spec wins):
- The brief ends with "See more" only. The image model printed a hint in brackets after it; leave that out.
- Sizes follow §1, not the image's 80 % scale.

**Floor:** today's lead page (dev review fixture, 8 Nov, 363 × 735; the v1.39 phone shot shows the same sheet).

**Style:** the Leads screen the owner approved (`../leads/approved-build-note8pro-20261108.webp`) and Dipak's Home
(`../home/`). The lead page reuses their components (`Avatar`, Home's card, the mint chip, `CallLens`, the tab bar) and does not
restyle them.

## 1. How to read the image

The image model draws everything at about 80 % of true size. Measured on `p5r-light.webp` (852 × 1846 px, 2.35 px per dp;
the boxes are in `measure-boxes.json`), against true size:

| Element | Measured in the image | Build (true size) | From |
|---|---|---|---|
| Side gutter | 9 dp | 16 dp | Home, Leads |
| Avatar | 42 dp | 48 dp | this spec |
| Name | ≈ 18 px on two lines | `--sx-text-xl` (22 px) 500, line height 28, wraps (at most 3 lines) | type scale |
| Fact line / follow-up line | ≈ 10 / 14 px | `--sx-text-sm` (15 px phone), 400 / 500 | type scale |
| Round action button | 38 dp | 48 dp circle in a 48 dp touch box, label `--sx-text-xs` under it | ux-audit T2, M3 |
| Card titles | ≈ 16 px | `--sx-text-md` (16.5 px phone) 500 | type scale |
| Brief label column | 90 dp | 96 dp | judges |
| Timeline icon | 20–23 dp | 24 dp disc in a 40 dp column on a 2 dp line | M3, benchmark |
| Call capsule | 37 dp | 56 dp | `call-lens.module.css` |
| Tab bar | 60 dp | 63 dp | Home |

Colours measured, with the token to use:

| Element | Measured | Token |
|---|---|---|
| Page | #ECF0F4 | `--sx-paper` |
| Cards | #FFFFFF, border #D4D8E0 | `--sx-surface`, 1 px `--sx-line` |
| Name / values | #000008 | `--sx-ink` |
| Fact line, brief labels, action labels | #384050–#404858 (8–10:1) | `--sx-muted` |
| Stepper (done, current), links | #006454, #005040 | `--sx-accent` |
| Upcoming chip | #E0F0EC, teal ink (6.7:1) | Home's `.chip[data-tone="good"]` |
| Call capsule | #006058 under white, 7.5:1 | `--sx-call-fill` / `--sx-call-ink` |

## 2. Layout at 363 × 735 (true size)

| y (dp) | Element | Height | Notes |
|---|---|---|---|
| 0–56 | Top bar | 56 | Back arrow (48 dp target) on the left, ⋯ on the right. No title: the name is in the header card. Back returns to the same row and scroll position in Leads. |
| 64–280 | Header card | ≈ 216 | 16 dp padding. Avatar 48, then the name, fact line and follow-up line; under them, the stage stepper. |
| 292–362 | Row of four | 70 | WhatsApp, Note, Follow-up, More: 48 dp circles with labels, spread evenly across the gutters. |
| 374–584 | "Before you call" card | ≈ 210 | Ends near the Call band at 363. Call history starts on the first scroll. |
| 600–672 | Call band | 56 + 8 + 8 | `CallLens` "Call <first name>", on the page colour. The page ends above it; nothing is ever under it. |
| 672–735 | Tab bar | 63 | Home's, with Leads active. |

At 363 × 735 the first viewport shows the header, the stage, the row of four and the whole brief. At 360 × 800 and 390 × 844,
the pinned upcoming row of the call history also shows. **One scroll container:** the page scrolls, and nothing behind it does (#172).

## 3. Components

**Top bar.** Back arrow and ⋯ (overflow: Edit details, Copy link, Reassign, Delete lead). Back keeps the place in Leads (the list
restores its scroll and the row stays highlighted for 1 s).

**Header card.** Home's card.
- The avatar sits left. The text column starts 12 dp after it:
  - the name in `--sx-text-xl` 500 `--sx-ink`, wrapping;
  - the fact line "City · Source · Side" in `--sx-muted`;
  - the follow-up line with a 16 dp calendar glyph and a pencil (a 48 dp target) that opens the follow-up picker. Late reads "Late · was due 2:00 pm" in `--sx-bad`, with "Late" in 500.
- **Stage stepper:** 16 dp under the text, full card width. It shows the organisation's main path in order (here New lead, Open, Interested, Meeting scheduled, Meeting done, Won):
  - done steps are 16 dp `--sx-accent` dots with a white check;
  - the current step is a 20 dp ring, its label in `--sx-accent` 500;
  - steps ahead are 14 dp `--sx-line-strong` rings;
  - a 2 dp line joins the dots: teal up to the current step, grey after it.
- Labels sit under the dots in `--sx-text-xs`, up to two lines, never inside a shape.
- Tapping a step asks first ("Move to Meeting scheduled?"), then moves the stage.
- Lost and Junk are not on the path. They live in More, under "Close as lost / junk". A closed lead shows its state as a chip in place of the stepper.

**Row of four.** Today's `ActionBox`, restyled as 48 dp neutral outline circles (1 px `--sx-line-strong`, 22 dp ink glyph) with
a `--sx-text-xs` `--sx-muted` label under each:
- WhatsApp: opens the chat (greyed, with "No phone number", when there isn't one);
- Note: opens `NoteBox`;
- Follow-up: opens the follow-up picker;
- More: opens the kit sheet, one 56 dp row each, in order: Ask Dipak about <name>, Add task, Upload recording, SMS, Email, Move stage, Reassign, Close as lost / junk.

Opening an item closes More first, so sheets never stack. Call is not in the row.

**"Before you call" card.** `prospect-information.tsx`'s first area ("What You Need to Know Now"), in Home's card:
- The title is `--sx-text-md` 500.
- The rows are a two-column grid: a 96 dp label column (`--sx-text-sm`, `--sx-muted`, sentence case) and values in `--sx-text-sm` `--sx-ink`, all starting at one indent, 8 dp between rows.
- Rows: Problem, Goal, Last talk (with its date and length under the label in `--sx-text-xs`), Next step.
- An unknown field reads "Not known yet" in `--sx-muted`; nothing is invented.
- "See more" (teal 500, no hint text after it) expands the other five areas in place, as Dipak asks (L1220–1222).

**Call history card.** Today's `History`, one column:
- Each event has a 24 dp disc (its kind's tint, 14 dp glyph) in a 40 dp column on a 2 dp line.
- The title is `--sx-text-sm` 500, with details under it in `--sx-text-xs` `--sx-muted`.
- The upcoming follow-up is pinned first, with a teal clock disc and Home's mint chip "Upcoming".
- Each call row is a whole tap target that opens that exact call.
- "View report" (when a report exists) and "Generate report" (only when a usable recording is unanalysed) are teal 500 text buttons at the row's right end, each with a 48 dp target. A missing recording reads "No recording · why", which opens the reason.
- No audio players, and no grey report bar.
- Day headers come back when there are more than 5 events.

**Latest note card.** The newest note: its text in `--sx-text-sm` `--sx-ink`, rendered as written (Marathi, Hindi or English), and
"<author> · <when>" in `--sx-text-xs` `--sx-muted`. Tapping it opens Notes.

**Call band.** `CallLens` as on Home and Leads: full width inside the gutters, 56 dp, labelled "Call <first name>" ("Call
Shrikant"). It is the one primary action on the page. A lead with no phone shows "Add a phone number" in the same place, as an outline button that opens Edit details, never a pinned bar over content (#178).

## 4. True-size budget

The image draws the history and the note above the fold; that is the 80 % scale. At true size the header card is about 216 dp,
because the name wraps onto two lines and the stepper labels onto two. The first viewport at 363 ends with the brief, and the history
starts on the first scroll. That still meets LP1: the name, follow-up, stage, brief and Call are all visible without scrolling.

## 5. Other sizes and states

| Size / state | Behaviour |
|---|---|
| 360 × 800, 390 × 844 | Same layout. The brief and the pinned upcoming row show. |
| 1440 × 900 | Today's desktop frame stays. The page opens in the list's side pane (no sheet). The header card, row of four and brief sit in a 560 dp column; the history goes under it. An image follows once the owner picks. |
| 130 % / 200 % text | The name wraps to 3 lines and stepper labels to 2. The row's labels wrap inside their 80 dp cells. The brief's label column grows to 120 dp at 200 %. The Call label wraps to its own line (v1.38 rule). |
| Dark | Home's dark tokens. The Call is `#2dd4bf` with a near-black label, and the stepper and links use the bright teal. Image: `p5r-dark.webp`. |
| No phone | WhatsApp is greyed with "No phone number". The band reads "Add a phone number". |
| New lead, no calls | The brief shows "Why they enquired" and "No previous conversation". History holds "Lead came in". |
| Viewer (no edit rights) | No Note, Follow-up or stepper taps. More holds only Ask Dipak and Copy link. |
| Closed (Won / Lost / Junk) | A chip in place of the stepper, no follow-up line, and the band reads "Call again" in outline. |

## 6. Asks covered

| Ask | How |
|---|---|
| Dipak: top summary (name, contact, problem, goal, last talk, concern, next step), kept short | Header card plus the "Before you call" card, with See more for the five other areas |
| Dipak 31 Oct: stage as a step strip, not a dropdown | The stepper in the header card, which asks before it moves the lead |
| Dipak: call history with recording and report status, one tap to the exact call or report | The call history card, with View and Generate report on their calls |
| Dipak: Ask Dipak about this customer; Upload recording reachable | More: "Ask Dipak about Shrikant", "Upload recording" |
| Dipak: Back keeps the place | The top bar's back returns to the same row and scroll position in Leads |
| Orchestrator 3 Nov: row of four (WhatsApp, Note, Follow-up, More), Call the one primary | The row of four and the Call band |
| #149, #177: action grid clutter | 8 icons become 4 |
| #172: two scrollbars | A page with one scroll container, not a sheet |
| #178: the "Add a phone number" bar covers content | Inline in the band's place |
