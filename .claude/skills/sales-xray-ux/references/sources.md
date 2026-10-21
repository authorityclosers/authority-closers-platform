# Sources and what we adopted

Read on the web on 22 Oct 2026. Nothing was copied or installed; every rule in this skill is in
our own words. Star counts are approximate, from the GitHub pages that day.

## Agent skills and guidelines

- **Vercel Web Interface Guidelines** (github.com/vercel-labs/web-interface-guidelines, MIT;
  review skill in vercel-labs/agent-skills): 44 px targets, 16 px inputs, never disable zoom,
  overscroll contained in sheets, state in the address, one request per submit.
- **Emil Kowalski skills, `mobile-native`** (github.com/emilkowalski/skills, MIT, ~48k stars):
  `dvh` app frames, `touch-action: manipulation`, explicit pressed state, hover only for fine
  pointers, short animations with faster exits.
- **Cap-go Capacitor skills** (github.com/Cap-go/capgo-skills, MIT): safe-area values set once
  with a fallback for old WebViews, bottom bars above the keyboard, check first and last fields.
- **Taste skill, `references/app-screens.md`** (github.com/Leonxlnx/taste-skill, MIT, ~100k
  stars): tables become two-line rows on phones, header actions fold into a menu except the
  primary, a dash for missing values and "0" for real zeros. Not adopted: near-black primaries
  and minimal colour (conflicts with our vibrant rule).
- **Impeccable** (github.com/pbakaus/impeccable, Apache-2.0, ~84k stars): one failing block never
  blanks a screen, `min-width: 0`, long-name tests, debounced search. Not installed: it sends
  usage data by default.
- **ibelick `baseline-ui`** (github.com/ibelick/ui-skills, MIT): skeletons shaped like the real
  layout, `tabular-nums`, an empty state with one next action.
- **UI/UX Pro Max** (github.com/nextlevelbuilder/ui-ux-pro-max-skill, MIT, ~138k stars, the most
  starred): five tabs or fewer, SVG icons not emoji, layout shift under 0.1. Not adopted: its
  stock icon sets and palette generator.
- **Anthropic `frontend-design`** (github.com/anthropics/skills, Apache-2.0): copy from the
  user's side, buttons that name the action, errors that say how to fix, avoid generic "AI"
  looks. Not adopted: a new look per brief (we have a design system).

## Mobile heuristics

- **NN/g, 10 usability heuristics** (nngroup.com/articles/ten-usability-heuristics): visible
  status, Undo, the same label for the same action everywhere.
- **NN/g, bottom sheets** (nngroup.com/articles/bottom-sheet): a visible X, Back closes, a scrim,
  never stack sheets, no long reading or long forms in a sheet.
- **NN/g, accidental overlay dismissal**: Back returns to the previous view; every close behaves
  the same.
- **NN/g, contextual swipe**: one meaning per direction, never the only path, Undo for
  destructive swipes, keep the item's name visible.
- **NN/g, empty states**: never blank, never while loading, say how to fill it, one action.
- **NN/g, tabs used right**: one or two words, sentence case, one row, two cues for the chosen
  tab, most used first.
- **NN/g, filters on mobile**: collect choices and Apply, counts beside values, applied filters
  as chips.
- **NN/g, dashboards and preattentive processing**: bars and lines, sorted; no pies, gauges or
  3D; colour never alone; the key numbers fit one screen.
- **NN/g, touch target size** and **skeleton screens**: about 1 cm targets; skeletons that match
  the real layout; nothing for loads under a second.
- **Material 3** (m3.material.io; numbers from the Material Components Android docs): 3 to 5
  navigation destinations with icon and label, one constructive create entry, chips 32 dp tall
  with 48 dp targets, sheets open at half height and close on Back, one snackbar at a time.
- **Android predictive back** (developer.android.com): temporary surfaces close before
  navigation; nothing tappable in the gesture insets. **Capacitor App plugin**
  (capacitorjs.com/docs/apis/app): a `backButton` listener must call `history.back()` itself.
- **Steven Hoober, UXmatters** (2013, 2017): grips change often; the centre is the most accurate
  area; tabs, search and create belong on the top or bottom edges.
- **Smashing Magazine, back button UX** (2022): a history entry only for overlays that feel like
  a separate view; confirm before Back throws away input.
- **web.dev**: viewport units, `interactive-widget`, `overscroll-behavior`, safe-area insets.

## Mobile CRM and sales apps

From public help centres (most reliable), release notes, product pages and store listings.

- **Pipedrive** (support.pipedrive.com, Focus view and call logging articles): the app opens on
  a focus screen with overdue counts first; a summary screen after each answered call asks for
  notes and the next activity.
- **HubSpot** (knowledge.hubspot.com, mobile tasks, calling and records articles): a Today tab
  of due and overdue tasks with Call on each row; a Log call sheet opens on hang-up and keeps
  notes typed during the call; the stage changes by tapping the stage under the name.
- **Close** (help.close.com, mobile app, Inbox and Outcomes articles): five bottom tabs; one
  inbox for missed calls, messages and due tasks with Done and Snooze; outcomes only for
  connected calls; an unlogged call stays visible; only a few fixed reports on phones.
- **Zoho Bigin and Zoho CRM** (help.zoho.com, bigin.com): fixed views such as Today plus
  Overdue; stage columns you swipe through; a Log call prompt when a call ends; row swipe
  actions with a full swipe running the outer action.
- **Privyr** (help.privyr.com): ad leads marked uncontacted until the first call or message;
  every lead always has a follow-up date with quick presets; contact buttons greyed out when the
  detail is missing; a duplicate warning when adding someone who exists.
- **LeadSquared, Freshsales, TeleCRM** (help pages and marketing pages): an outcome form after
  calls, including unknown numbers; pick a recent call from the call log to create a lead; a
  "call later" list sorted nearest first; seller leaderboards for owners.
- Not adopted: drag-only kanban on phones, and swipe directions that change by record type. We
  keep one meaning per direction (right calls, left messages), as already built.

## Already installed, not repeated here

- **apple-design** skill: Apple HIG, 123 pages, plus a design-craft lens.
- **design-md-library** skill: 84 brand DESIGN.md write-ups (VoltAgent awesome-design-md, MIT).
