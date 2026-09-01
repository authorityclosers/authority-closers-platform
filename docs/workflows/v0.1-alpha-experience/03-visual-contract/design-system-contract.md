# Clarity Grid design-system contract

Status: selected visual direction and implementation contract. It is not a
claim that the current runtime matches every reference.

## 1. Source direction

Use `DIRECTION-A-Clarity-Grid.png` (Drive ID
`1VOgXqLvaslXPwYM8bzqboUVQe-JYdT39`) as the selected system. Study OS and
Signal Path remain reserve concepts. Screen-family references are registered
in `../05-handoff-qa/asset-manifest.json`.

Source matching rules:

- Attach the exact approved reference for the screen family before generating
  or implementing pixels.
- Preserve the blue/white grid logic, crisp information hierarchy, compact
  utility styling, and restrained shape language visible in Clarity Grid.
- Do not invent brand hex values, typography assets, gradients, illustrations,
  icons, radii, or card density not established by the source.
- Use a maintained icon library for interface icons. Do not replace assets with
  emoji, ASCII, CSS drawings, approximate SVGs, or placeholder boxes.
- Compare reference and implementation at the same viewport and state.

## 2. Visual principles

- Learner: calm, directional, low cognitive load, strong next-action clarity.
- Learning workspace: content-first with continuous activity/progress context.
- Admin: dense, explicit, auditable; unknown values and risky actions are
  unmistakable.
- Status is always text/icon/structure plus color, never color alone.
- Missing data is visually distinct from zero.
- Themes change presentation, not information hierarchy or semantics.

## 3. Semantic token contract

The approved UI specification freezes semantic roles, not final brand values.
Implement these roles in both light and dark themes; extract actual values from
approved assets/code tokens during implementation review.

| Token family       | Required roles                                  | Rule                                                 |
| ------------------ | ----------------------------------------------- | ---------------------------------------------------- |
| `color.brand.*`    | primary, strong, subtle, on-brand               | values require approved source extraction            |
| `color.surface.*`  | canvas, section, card, elevated, overlay        | maintain hierarchy in both themes                    |
| `color.text.*`     | primary, secondary, muted, inverse, link        | WCAG contrast in each state/theme                    |
| `color.border.*`   | subtle, default, strong, focus                  | focus remains visible on all surfaces                |
| `color.semantic.*` | info, success, warning, danger, locked, offline | never sole status signal                             |
| `space.0..12`      | 4px-based scale                                 | no arbitrary per-screen spacing                      |
| `radius.*`         | small, medium, large, full                      | match Clarity Grid source; no ornamental inflation   |
| `shadow.*`         | none, raised, overlay                           | use sparingly; borders/grouping carry most structure |
| `type.*`           | xs through 4xl semantic scale                   | final font requires approved asset/license source    |
| `motion.*`         | fast, base, slow                                | 100-300ms; disabled/reduced when requested           |

No literal token value in a generated screen becomes authoritative until it is
measured against the approved reference and recorded in implementation code.

## 4. Theme contract

Choices: `light`, `dark`, `system`.

- `system` is the default and resolves with `prefers-color-scheme`.
- The stored choice and resolved theme are different concepts. A System choice
  may resolve to Light or Dark as the environment changes.
- Apply `color-scheme` to browser-provided controls and provide matching theme
  metadata early enough to avoid a first-paint flash.
- All semantic tokens, focus states, form controls, charts/progress, skeletons,
  disabled/locked states, overlays, media controls, and email/web handoff
  screens need explicit light and dark checks.
- Images/logos must use an approved variant or a verified neutral treatment;
  never invert a logo blindly.
- Dark mode is not a black background substitution. Preserve the Clarity Grid
  hierarchy and avoid low-contrast gray-on-gray controls.
- The selected preference changes presentation only. It cannot change content,
  route availability, permissions, completion, or data.

Persistence boundary: the current implementation stores only the non-sensitive
`light`/`dark`/`system` choice in device-local storage under
`ac-appearance-theme`. It is a `runtime_pending` implementation candidate, not
live proof. Cross-device/account persistence and learner/admin synchronization
are not authorized or inferred by this package.

## 5. Responsive composition

| Mode        | Width                | Learner composition                                                  | Admin composition                                      |
| ----------- | -------------------- | -------------------------------------------------------------------- | ------------------------------------------------------ |
| Compact     | `<600px`             | single column, safe-area bottom nav, full-width primary action       | cards/disclosures; no forced wide table                |
| Medium      | `600-1023px`         | compact nav, wider form/course content                               | rail may collapse; prioritized columns                 |
| Wide        | `>=1024px`           | persistent rail, constrained reading column, optional activity split | persistent rail, tables/split panes                    |
| Dense admin | `>=1280px` preferred | not applicable                                                       | comparison/detail panes while keyboard/zoom accessible |

Reference checks use 390x844 and 1440x900. Additional checks must cover 320px,
375px, 768px, 1024px, 1280px, long copy, browser zoom, Windows display scaling,
and iOS safe-area insets.

## 6. Component register

| Component ID | Component             | Required states/contract                                             |
| ------------ | --------------------- | -------------------------------------------------------------------- |
| `UI-C001`    | `AppShell`            | wide/compact, loading, offline banner, session-expired return        |
| `UI-C002`    | `AuthShell`           | split/stacked, provider retry, legal/consent links                   |
| `UI-C003`    | `PrimaryNav`          | current, available, disabled-with-reason, focus, compact             |
| `UI-C004`    | `ThemeControl`        | Light/Dark/System selected, resolved label, keyboard radio semantics |
| `UI-C005`    | `ProgressSummary`     | known value, unavailable, loading, completed; no mastery inference   |
| `UI-C006`    | `ModuleCard`          | available, current, in-progress, completed, locked-with-reason       |
| `UI-C007`    | `ActivityRow`         | type, order, required, status, lock reason, current action           |
| `UI-C008`    | `ActivityShell`       | loading, ready, saving/processing, error, offline, completed         |
| `UI-C009`    | `VideoActivity`       | media loading/error, coverage, captions/transcript, evidence pending |
| `UI-C010`    | `DraftTextResponse`   | restored, dirty, saving, saved, failed, offline, conflict, completed |
| `UI-C011`    | `ChallengeCard`       | instructions, acknowledged, evidence ready, submitted, error         |
| `UI-C012`    | `CompletionChecklist` | incomplete reasons, evaluating, complete                             |
| `UI-C013`    | `SaveStatus`          | non-color icon/text, timestamp/revision, live announcement           |
| `UI-C014`    | `LockedState`         | exact safe reason, prerequisite action, no protected payload         |
| `UI-C015`    | `ErrorRecoveryPanel`  | retry, restart, support; preserved-input statement                   |
| `UI-C016`    | `SettingsSection`     | Profile, Appearance, Security, Privacy; dirty/saved/error            |
| `UI-C017`    | `AdminTable`          | loading, empty, unavailable, permission, pagination when real        |
| `UI-C018`    | `AdminDetailPanel`    | tenant/resource context, freshness, audit trail, close/focus return  |
| `UI-C019`    | `ReasonConfirmDialog` | named action, consequence, reason, cancel, processing, result        |
| `UI-C020`    | `AuditBanner`         | operator, tenant, purpose, read-only/view-as state                   |
| `UI-C021`    | `OfflineBanner`       | stale timestamp, blocked mutation, reconnect status                  |
| `UI-C022`    | `ToastStatus`         | supplemental only; never the sole durable mutation result            |

## 7. Forms and content

- Every control has a persistent visible label unless the compact visual still
  provides an equally clear accessible name and context.
- Required/optional status is textual. Errors are associated with fields and a
  summary/focus path where multiple fields fail.
- Password managers are supported; authentication does not rely on memory
  puzzles or blocking paste.
- Long reflection/evidence text is mobile-friendly and keyboard-friendly.
- Destructive or high-risk admin actions are visually separated from routine
  settings and require reason/confirmation where the command contract says so.

## 8. Motion and feedback

- Motion supports orientation and state change; no decorative dependency.
- Respect `prefers-reduced-motion`; disable nonessential transitions and avoid
  auto-advancing content.
- Loading skeletons match final structure and do not animate indefinitely for
  a canonical business uncertainty.
- Save/completion feedback remains visible after transient toast dismissal.

## 9. Accessibility acceptance

- WCAG 2.2 AA is the target, including visible/non-obscured focus, accessible
  authentication, error identification, redundant-entry reduction, and minimum
  target sizing.
- AC mobile design intent remains approximately 44x44 CSS px for interactive
  targets; the normative WCAG 2.2 minimum/spacing criteria still require test.
- Logical DOM/focus order matches visual order in both rails and activity split
  views.
- Icon-only controls have accessible names; state announcements use restrained
  live regions.
- Text and controls survive zoom/reflow; captions/transcripts and player
  controls remain reachable.
- Theme contrast, forced colors/high contrast where supported, reduced motion,
  and non-color state cues are release checks.

## 10. Visual QA method

For each implemented screen/state:

1. Attach the exact reference from the asset manifest.
2. Capture the implementation at the same viewport and state.
3. Compare the two in one review input.
4. Check layout, crop, padding, margin, type size/weight, borders/radii, icons,
   state copy, focus, and responsive hierarchy.
5. Fix the highest-impact mismatch and repeat.
6. Mark the asset `reference`, `selected`, `superseded`, or `approved`; never
   call it approved from a screenshot alone.
