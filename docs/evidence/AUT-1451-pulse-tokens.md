# AUT-1451 Evidence: Scoped Pulse-Role Teal Adapter and Operational Density Tokens

## Summary
- **Task**: AUT-1451 (Design 1 / card 2)
- **Lane**: `ui`
- **Goal**: Add the scoped Pulse-role to Sales Xray teal adapter and operational density tokens described in study section 3, card 2 of `/home/acdev/scratch/ea-study/reports/r6-pulse-latest-design.md`.
- **Result**:
  - All 20 Pulse semantic `--theme-*` roles declared and scoped in `apps/sales-xray-web/app/ui/pulse-tokens.css`.
  - Roles map 100% to Sales Xray's authoritative `--lx-*` teal and neutral tokens; no iris actions, no circular aliases.
  - Keyboard focus remains teal (`--theme-focus: var(--lx-teal)`); coaching focus remains orange (`--lx-focus: #b45309` in light, `#f59e0b` in dark).
  - Operational density tokens declared in `apps/sales-xray-web/app/lightbox/tokens.css:26` and mirrored in `apps/sales-xray-web/app/styles.css` embed scope:
    - `--lx-control-compact-h: 32px`
    - `--lx-control-h: 36px`
    - `--lx-table-head-h: 36px`
    - `--lx-row-min-h: 44px`
    - `--lx-panel-head-min-h: 48px`
    - `--lx-tile-min-h: 96px`
    - Matching `--lx-density-*` aliases.
  - `apps/sales-xray-web/app/styles.css` imports `pulse-tokens.css` via `@import "./ui/pulse-tokens.css";`.
  - Embed boundaries, script rules (`[data-script="deva"]`), Hindi/Marathi typography, and owner-approved surfaces remain intact.

## Token Role Mapping (20 Pulse Semantic Roles)

| Pulse Role (`--theme-*`) | Sales Xray Adapted Token | Light Value | Dark Value | Notes |
|---|---|---|---|---|
| `--theme-canvas` | `var(--lx-paper)` | `#f4f6fb` | `#060a14` | Neutral app background |
| `--theme-surface` | `var(--lx-surface)` | `#ffffff` | `#0f1829` | Cards / panels |
| `--theme-surface-subtle` | `var(--lx-sunken)` | `#edf1f7` | `#0a1120` | Wells / segmented containers |
| `--theme-text` | `var(--lx-ink)` | `#0b1424` | `#e8edf5` | Primary text |
| `--theme-text-muted` | `var(--lx-muted)` | `#56637a` | `#93a0b5` | Muted / secondary text |
| `--theme-border` | `var(--lx-line)` | `#e2e7f0` | `#1e2a42` | Hairlines / standard borders |
| `--theme-border-strong` | `var(--lx-line-strong)` | `#cbd3e1` | `#2b3a59` | Emphasized borders |
| `--theme-action` | `var(--lx-teal)` | `#097870` | `#2dd4bf` | Primary action (Teal, never Iris) |
| `--theme-action-hover` | `var(--lx-teal-hover)` | `#06615b` | `#5eead4` | Primary hover state |
| `--theme-action-text` | `var(--lx-on-teal)` | `#ffffff` | `#0a1220` | Text on teal actions |
| `--theme-focus` | `var(--lx-teal)` | `#097870` | `#2dd4bf` | Focus outline; **never `--lx-focus`** |
| `--theme-brand-2` | `var(--lx-teal-2)` | `#14b8a6` | `#14b8a6` | Wordmark / subtle teal accent |
| `--theme-info` | `var(--lx-info)` | `#2459e0` | `#7aa7ff` | Semantic status |
| `--theme-success` | `var(--lx-success)` | `#097870` | `#2dd4bf` | Semantic status |
| `--theme-warning` | `var(--lx-warning)` | `#b45309` | `#f59e0b` | Semantic status |
| `--theme-danger` | `var(--lx-danger)` | `#c0261b` | `#f97066` | Semantic status |
| `--theme-disabled-surface` | `var(--lx-sunken)` | `#edf1f7` | `#0a1120` | Disabled container fill |
| `--theme-disabled-text` | `var(--lx-muted)` | `#56637a` | `#93a0b5` | Disabled text fill |
| `--theme-shadow` | `var(--lx-shadow-1)` | `0 1px 2px rgba(11, 20, 36, 0.05)` | `0 1px 2px rgba(11, 20, 36, 0.05)` | Compact panel elevation |
| `--theme-transition-duration` | `var(--lx-dur-quick)` | `120ms` | `120ms` | 0ms under reduced motion |

## Verification Evidence

### 1. Lightbox Tokens Test Suite (`app/lightbox/tokens.test.ts`)
```
✓ app/lightbox/tokens.test.ts (12 tests) 399ms
  ✓ Lightbox token derivative (12)
    ✓ keeps every source token except the documented corrections
    ✓ documents real source failures that the corrections resolve
    ✓ gives every small-text pair at least 4.5:1 in light, including alpha fills
    ✓ gives every small-text pair at least 4.5:1 in dark, including alpha fills
    ✓ mirrors the light tokens into an embed scope the standalone root skips
    ✓ keeps a light report surface coherent inside a dark app theme
    ✓ keeps new Lightbox modules on tokens, never raw hex colours
    ✓ Scoped Pulse-role to Sales Xray teal adapter (AUT-1451 card 2) (5)
      ✓ declares all 20 Pulse semantic roles in ui/pulse-tokens.css
      ✓ maps Pulse roles strictly to Sales Xray teal/neutral tokens without iris or circular aliases
      ✓ scopes the adapter so global :root is not polluted
      ✓ is imported in styles.css via scoped import
      ✓ resolves operational density tokens on adapted components and in root

Test Files  1 passed (1)
     Tests  12 passed (12)
```

### 2. Integrated Styles Boundary Test (`app/styles.integration.test.ts`)
```
✓ app/styles.integration.test.ts (2 tests) 16ms
  ✓ integrated Sales Xray boundary (2)
    ✓ keeps generic Sales Xray rules inside the component scope
    ✓ uses the real learner route without query supplied scope

Test Files  1 passed (1)
     Tests  2 passed (2)
```

### 3. Owner-Approved Surfaces Guard (`app/owner-surfaces.test.tsx`)
```
✓ app/owner-surfaces.test.tsx (3 tests) 1401ms
  ✓ keeps every owner-approved report section
  ✓ keeps every owner-approved Document section, in order
  ✓ keeps the Calls workspace controls

Test Files  1 passed (1)
     Tests  3 passed (3)
```

### 4. Code Formatting
Prettier ran cleanly on all modified and new files:
- `apps/sales-xray-web/app/ui/pulse-tokens.css`
- `apps/sales-xray-web/app/lightbox/tokens.css`
- `apps/sales-xray-web/app/styles.css`
- `apps/sales-xray-web/app/lightbox/tokens.test.ts`
