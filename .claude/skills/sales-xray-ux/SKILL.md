---
name: sales-xray-ux
description: >
  Phone-first UX rules, screen-by-screen checklists and a 0-3 screenshot rubric for Sales X-Ray,
  our sales CRM (Home, owner dashboard, Leads, Lead page, Calls, Call report, Chats, Settings and
  the + sheet), on phones and computers, in the browser and in the Android app. Use it before
  building or changing any Sales X-Ray screen, when reviewing Sales X-Ray screenshots or a UI merge
  (UI Guard), when the owner says a screen looks or works badly, and whenever you decide layout,
  navigation, sheets, back behaviour, swipe actions, chips, empty states, dashboards or charts.
  Pair it with apple-design for HIG review and design-md-library for visual references.
---

# Sales X-Ray UX

Sales X-Ray is used by salespeople on their phones between calls: one hand, in a hurry, often
outdoors. Owners and admins open it to see results. Judge every screen on a phone first
(360 to 412 px wide), then on a computer (1440 px). A screen is good when a seller knows the next
action, or an owner knows how sales are going, within two seconds.

## What to load with it

- **apple-design**: HIG-grounded review of components, accessibility, dark mode, motion and
  materials. This skill does not repeat it.
- **design-md-library**: brand write-ups (Linear, Superhuman, Stripe, Raycast and others) for
  colour, type, depth and motion ideas. Borrow principles, never another brand's look.
- `references/screen-checklists.md`: what each screen must have.
- `references/rubric.md`: the 0-3 scores that the builder and UI Guard give to screenshots.
- `references/implementation.md`: the kit to use and code recipes (back-to-close, overflow,
  safe areas, name casing, swipe rows).
- `references/sources.md`: where these rules came from.

The owner's standing rules win over anything here. Laptop sessions have them in memory
`feedback-sales-xray-ui-direction`; their essentials are in "House rules" below for agents
without that memory.

## Workflow

Builder:
1. Before coding, write one line: who the screen is for (seller, or owner/admin), its job, and
   its one primary action.
2. Open that screen's checklist in `references/screen-checklists.md`.
3. Build with the kit (`ds/`, `ui/sheet.tsx`, `ui/kit.tsx`, `--sx-*` tokens). See
   `references/implementation.md`.
4. Put it on the dev workbench and take the screenshot set from `references/rubric.md`: 390
   light and dark, 360, 1440, every overlay you touched, empty and loading states. Use real
   data where you can and review fixtures otherwise (see "Check your work").
5. Score it. Fix until it passes. Post the score table with the shots.

UI Guard: score the same set with the same rubric. A house-rule breach is a hold, whatever the
total. Name at most three fixes.

## The rules

### 1. One job, one primary action

- Each screen has exactly one filled primary button. Everything else is a secondary button, a
  chip, an icon button or an item in a menu.
- The label names the outcome and the object: "Call Priya", "Save and book next call",
  "Analyse call". Not "Submit", "OK" or "Continue".
- On phones the primary action sits in the bottom third: a sticky action bar above the tab bar,
  or the sheet footer. Never only in the top bar.
- The + is the only way to create things. No "+ New" buttons in page headers.

### 2. Thumb zone, and the + sheet

- Frequent actions live in the lower half of the screen. Tabs, search and + sit on the top or
  bottom edges. Rare and destructive actions go in an overflow menu, far from frequent ones.
- Phones have five tabs: Home, Leads, +, Calls, More. Each tab has an icon and a visible label.
  No swiping between tabs.
- The centre + is not a page. It opens the create sheet: a bottom sheet with 3 to 6 large rows
  (icon tile, label, one-line hint), most used first, such as Add lead, Analyse a call and Book
  a follow-up. Only list things the app really does.
- Touch targets are at least 44 x 44 px (48 px is better on Android), with 8 px between them.

### 3. Back closes every overlay

- Browser back, the Android back gesture and the hardware back key close the top overlay first:
  sheet, dialog, hold menu, picker, full-screen search, image viewer. One press closes one.
- The X, a tap on the scrim, a swipe down, Escape and Back all close the same way.
- Never stack sheets. A picker inside a sheet is a step within it.
- Tabs and filters change the address with `replaceState`, so Back never steps through toggles.
- Recipe and checks: `references/implementation.md`, "Back closes every overlay".

### 4. Fit the screen; never scroll sideways

- Everything works at 360 px. Nothing makes the page scroll sideways, ever.
- App screens fit the viewport (owner rule): the frame stays put and inner panels scroll.
- Long names, emails and numbers wrap or end with an ellipsis; the full value is one tap away.
- Tables become two-line rows on phones.

### 5. Stage tabs, not filter clutter

- Leads are organised by stage tabs with real counts. The stages come from the organisation's
  settings, never from code.
- One view switcher per screen: stage tabs, or a segmented control with 2 to 4 options.
- Other filters hide behind one Filter chip that shows how many are on. They open in a sheet
  with an Apply button. Filters that are on appear as removable chips.
- Filters, tab and search live in the address, so a refresh or a shared link keeps them.

### 6. Rows that read at a glance

- A row has an avatar or initial, the name, one context line (stage, source, last contact), one
  status chip and a time or due mark on the right. Two lines at most on phones.
- **Names are shown with capitals** ("Priya Shah", not "priya shah" or "PRIYA SHAH"), at display
  time, without rewriting stored data. Phone numbers are grouped ("+91 98765 43210"). Dates are
  relative ("Today 4:30 pm", "Yesterday").
- Tapping a row opens it. Back returns to the list at the same scroll position.

### 7. Swipe actions with icons

- Swipe right calls; swipe left messages. Each direction means the same thing on every list.
- The revealed area shows an icon and a one-word label on the action's colour, and the person's
  name stays visible.
- Every swipe action is also in the row's hold menu and on the lead page. Swiping is a shortcut,
  never the only way. A swipe never starts at the screen edge, where it would fight the Android
  back gesture.
- A contact action that cannot work (no phone number) shows greyed out with a hint, not hidden.
- Anything that cannot be undone asks first, or offers Undo in a corner card.

### 8. Compact chips, not wide buttons

- Secondary actions are compact chips: an icon plus one or two words, about 32 px tall with a
  44 px hit area. Full-width buttons are only for the one primary action.
- A chip that sets a value opens its picker in place (a small sheet or menu).
- Chips wrap onto a second line, or sit in one deliberate scroll strip. Never stack toggles.

### 9. Empty states say how to start

- Every empty area says what goes there and how to fill it, with exactly one action button:
  "No leads yet. Add your first lead or connect your ad form." [Add lead]
- Write each case separately: first use, all done ("All caught up. Next call at 4:30 pm"), and
  no results ("No leads match. Clear filters").
- Never show an empty state while data is still loading. Hide tiles that would show zero on a
  new account; show a start card instead.

### 10. Loading and errors feel calm

- Loading shows a skeleton in the final layout, at the final sizes. Nothing jumps when the data
  arrives. Nothing from the previous lead or call flashes on screen.
- App-level problems are small corner cards that retry by themselves (`notify()`), never a
  banner or a full-page error. Only field validation sits inline under the field.

### 11. Seller Home leads with next actions

- The top of a seller's Home is the Today list: count chips (Late, Due today, New), then Late,
  Call now and Later today, and one primary action ("Start calling" or "Call <next name>").
  Late items are never hidden.
- Each row has a one-tap Call. New leads carry a "New" chip until the first call or message.
- Calls without an outcome show as one item ("Log 2 calls"), so nothing is lost.
- Below it, a small strip of today's real numbers (calls made, connected, follow-ups booked).
- No big greeting, no marketing tiles, nothing the seller cannot act on.

### 12. Owner and admin dashboard leads with sales outcomes

- The top shows the period's outcomes: won or closed, meetings or visits booked, new leads,
  connect rate and first-response time. Four or five numbers in two columns, each with a trend
  chip against the last period.
- Then sellers ranked by outcome, each row opening that seller's profile. Then the stage funnel.
  Activity counts (calls, talk time) come last. Three or four fixed cards on phones; building
  custom reports stays on computers.
- A period switch (Today, 7 days, 30 days) sits at the top as one segmented control.
- Sales value appears only if the organisation records it. Never our own prices or costs.

### 13. Charts that read at a glance

- One question per chart. The title states the answer: "Calls up 12% on last week".
- Use bars and lines; sort bars. No pies or donuts with more than two parts, no gauges, no 3D.
  A single share ring for one proportion is fine.
- At most seven bars on a phone. Label the key value directly; tapping a bar shows its number.
- Series pass 3:1 against the card; colour never carries meaning alone.
- Only real numbers. A missing value is a grey dash; a real zero shows "0".

### 14. Words

- Plain words at grade 8 to 10. Sentence case everywhere; no ALL CAPS labels.
- Tab labels have one or two words; buttons four or fewer. No exclamation marks.
- Never show IDs, raw status codes, transcript references or internal names.
- Numbers carry units ("12 calls", "3 min"). Durations are in words ("2 hours ago").

### 15. Every call ends with an outcome; every lead has a next step

- When a call ends, an outcome sheet opens by itself. Connected calls get 4 to 6 one-tap outcomes
  and a next-call picker; unanswered calls get one "No answer · try again" chip with a time.
- Notes typed during the call carry over. "Save and book next call" is the primary.
- Every open lead always has a next call date. Quick picks: in 1 hour, this evening, tomorrow,
  in 3 days, next week, pick a date.
- A stage changes from the stage chip on the lead page, through a sheet listing every stage;
  Won and Lost are always in it. Phones never need drag-and-drop.

## House rules (any breach is a hold)

- No prices, costs, minutes charged or "valid until" times on any user screen. Admin only.
- No customer or organisation names in UI copy, code, fixtures or file names. Use fictional
  names in tests and fixtures.
- No emoji. Icons are our own line SVGs (`IconBadge`, `IconTile`).
- App-level errors are corner cards.
- Vibrant, professional colour from `--sx-*` tokens, never raw hex. Text passes 4.5:1, chart
  series 3:1, in light and dark. Light and dark share one layout.
- Only real data. No invented numbers, waveforms, scores or trends.
- The app frame persists between screens and nothing shifts on load. Motion is calm and respects
  reduced motion.

## The ten rules that fix most owner complaints

1. One filled primary action per screen, in the bottom third on phones.
2. The + tab opens a bottom sheet of create actions; no other create buttons.
3. Back (button, gesture, key) closes the top overlay first, one per press.
4. Nothing scrolls sideways at 360 px; app screens fit the viewport.
5. Stage tabs with counts on Leads; every other filter behind one Filter chip.
6. Names shown with capitals; phone numbers grouped; dates relative.
7. Compact icon chips instead of wide secondary buttons.
8. Every empty state says how to start and has one action.
9. Swipe right to call, left to message, with icon and label, plus a hold menu.
10. Seller Home starts with the Today list; owner dashboard starts with sales outcomes.

## Check your work

- Shots come from the dev workbench: `ssh ac wb-ci --visual` renders the review fixtures
  (`/review-fixture/...`) at phone and computer sizes, light and dark, on GitHub's runners. Add
  or extend a fixture when your screen has none.
- No heavy checks on ac (owner order, 20 Oct): no tsc, eslint, vitest, pytest or Playwright
  suites there. At most one quick single-page shot under `nice -n 19 ionice -c3`; never a full
  sweep. The overflow probe in `references/implementation.md` runs in any browser console.
- Post the rubric table with the shots. If you cannot take a shot, say which and why; never
  score what you did not see.
