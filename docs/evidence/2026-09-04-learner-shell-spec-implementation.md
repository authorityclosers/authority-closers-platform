# Learner Shell & Sidebar Visual Spec Implementation Evidence — 2026-09-04

## Outcome

The learner desktop and mobile shell in `apps/learner-web` has been fully implemented and verified against the approved visual specification (`closers-academy-learner-shell-spec.png` / `closers-academy-learner-shell-spec.svg`).

The implementation refines the Direction A command-center architecture, synchronizes token hierarchies across light and dark modes, establishes a 280 px expanded / 76 px collapsed rail with smooth 180 ms transitions, introduces an overlay collapse toggle, renders body-portal floating tooltips in the collapsed state, styles the utility header with transparent backdrop and aligned 76 px height, and updates the mobile brand header hierarchy.

All existing and targeted test suites pass cleanly under the required Node 24 runtime, with zero typecheck errors, zero ESLint warnings, and a successful production build.

---

## Visual Authority & Design Reference

Implementation strictly conforms to the approved design deliverables:
- **Primary Design Specification PNG**:
  `C:\Users\Suyash\.codex\visualizations\2026\09\04\01a06c32-45d7-7d80-baee-77e1a80a88f4\closers-academy-learner-shell-spec.png`
- **Primary Design Specification SVG**:
  `C:\Users\Suyash\.codex\visualizations\2026\09\04\01a06c32-45d7-7d80-baee-77e1a80a88f4\closers-academy-learner-shell-spec.svg`
- **Direction A Shell Foundation**:
  `docs/workflows/learner-product-v1/03-visual-exploration/selection.md`
  `docs/workflows/learner-product-v1/03-visual-exploration/direction-a-command-center-desktop.png`

---

## Implementation Details

### 1. Sidebar Geometry & Interaction Tokens (`learner-next-slice.css`)
- **Dimensions**:
  - Expanded width: `--sidebar-width-expanded: 280px;` (updated from 260px).
  - Collapsed width: `--sidebar-width-collapsed: 76px;` (updated from 72px).
  - Active rail width: `--sidebar-active-rail-width: 3px;`.
  - Transition duration: `--sidebar-duration-normal: 180ms;`.
- **Theme Synchronization**:
  - Light mode:
    - `--sidebar-bg: var(--theme-surface, #ffffff);`
    - `--sidebar-border: var(--theme-border, #d7deea);`
    - `--sidebar-text: var(--theme-text, #0f1b33);`
    - `--sidebar-text-muted: var(--theme-text-muted, #596579);`
    - `--sidebar-hover-bg: #f7f8fa;`
    - `--sidebar-mark-cut: #eef3ff;`
  - Dark mode (`html[data-theme="dark"]`):
    - `--sidebar-bg: var(--theme-surface, #101a2b);`
    - `--sidebar-border: var(--theme-border, #34425a);`
    - `--sidebar-text: var(--theme-text, #edf2fb);`
    - `--sidebar-text-muted: var(--theme-text-muted, #b6c0d2);`
    - `--sidebar-hover-bg: rgba(255, 255, 255, 0.06);`
    - `--sidebar-active-tint: rgba(155, 179, 255, 0.12);`
    - `--sidebar-rail-accent: var(--theme-action, #9bb3ff);`
    - `--sidebar-mark-cut: #142036;`
- **Brand Mark Cutout Token**:
  - Bound `--ac-mark-cut: var(--sidebar-mark-cut, #eef3ff)` in light mode and `#142036` in dark mode, ensuring the `BrandMark` hexagon badge displays the proper inner cutout color on dark backgrounds.

### 2. Overlay Collapse Toggle (`site-shell.tsx` & `learner-next-slice.css`)
- **Expanded state**:
  - Toggle button `.learner-sidebar-toggle` positioned absolutely at `top: 50%; right: 14px; transform: translateY(-50%)` inside the sidebar header.
  - Hidden at rest (`opacity: 0; pointer-events: none;`) to maintain clean brand presentation.
  - Smoothly revealed on `.learner-sidebar:hover`, `.learner-sidebar:focus-within`, and `.learner-sidebar-toggle:focus-visible` (`opacity: 1; pointer-events: auto;`).
- **Collapsed state**:
  - Toggle button centered over the compact brand mark (`left: 50%; top: 50%; transform: translate(-50%, -50%); width: 38px; height: 38px; border-radius: 10px;`).
  - Concealed at rest; on hover or keyboard focus, overlays the brand mark with an accessible chevron expand button.
- **Accessibility**:
  - Includes `aria-label="Expand sidebar"` / `aria-label="Collapse sidebar"`.
  - Accessible via keyboard navigation (`focus-visible` ring).
  - Included in `@media (prefers-reduced-motion: reduce)`.

### 3. Portal Tooltips in Collapsed Rail (`site-shell.tsx` & `learner-next-slice.css`)
- Rendered using `createPortal(..., document.body)` so tooltips float above all DOM stacking contexts.
- High z-index (`z-index: 99999`) prevents clipping behind page headers, cards, or video elements.
- Accessible attributes: `role="tooltip"`, unique ID matching trigger `aria-describedby`.
- Displayed for navigation items, the search trigger, and account items (Profile, Settings, Help) on hover and focus.

### 4. Utility Header & Search Trigger (`site-shell.tsx` & `learner-next-slice.css`)
- **Header Geometry**:
  - Height set to `76px` to align with the collapsed sidebar header height.
  - Background set to transparent (`--header-bg: transparent; backdrop-filter: blur(12px); -webkit-backdrop-filter: blur(12px);`).
  - Subtle bottom border matching `--header-border` token.
- **Header Search Trigger**:
  - Display text: `"Search for courses, lessons, and more"`.
  - Shortcut badge: `<kbd>⌘ K</kbd>`.
  - Full-width styling with subtle surface background, hover brightening, and focus-visible outline.
- **Sidebar Search Trigger**:
  - Display text: `"Search"`.
  - Shortcut badge: `<kbd>⌘K</kbd>`.

### 5. Navigation Items & Account Section
- **Nav Items**:
  - Active rail: `3px` solid accent rail on left edge (`--sidebar-rail-accent`).
  - Border radius: `10px` rounded pill styling.
  - Active text/icon tinting configured for both light and dark themes with high contrast.
- **Account Section**:
  - Preserved Profile, Settings, and Help links in both `workspaceSections` and collapsed footer representations, ensuring full compliance with both `learner-sidebar.test.tsx` and `direction-a-shell.test.ts`.
  - Profile link includes `title="Profile"`.
  - Settings link includes `title="Settings"`.
  - Help trigger button includes `title="Help"`.

### 6. Mobile Shell & Brand Attribution (`site-shell.tsx` & `learner-next-slice.css`)
- Mobile header brand features `Closers Academy` with `by Authority Closers` tenant attribution hierarchy:
  - `.mobile-brand-name`: Closers Academy
  - `.mobile-brand-tenant`: by Authority Closers
- Mobile bottom navigation bar retained with accessible touch targets.

---

## Verification & Test Results

All verification commands executed on Windows with Node.js 24.19.0 runtime (`C:\Users\Suyash\AppData\Local\OpenAI\Codex\runtimes\cua_node\c2900163265bdaec\bin\node.exe`) and pnpm 11.19.0.

### 1. Targeted Sidebar & Shell Tests
```powershell
$nodeDir = Split-Path $env:CODEX_MCP_NODE_PATH; $env:PATH = "$nodeDir;$env:PATH"
pnpm --filter learner-web test -- learner-sidebar.test.tsx
# Result: 36 passed (36)

pnpm --filter learner-web test -- learner-sidebar.dom.test.tsx
# Result: 3 passed (3)

pnpm --filter learner-web test -- direction-a-shell.test.ts
# Result: 53 passed (53)
```

### 2. Full Learner-Web Test Suite
```powershell
$nodeDir = Split-Path $env:CODEX_MCP_NODE_PATH; $env:PATH = "$nodeDir;$env:PATH"
pnpm --filter learner-web test
# Result: 31 test files passed, 468 tests passed (0 failed)
```

### 3. TypeScript Typecheck
```powershell
$nodeDir = Split-Path $env:CODEX_MCP_NODE_PATH; $env:PATH = "$nodeDir;$env:PATH"
pnpm --filter learner-web typecheck
# Result: Process exited with code 0 (clean, 0 errors)
```

### 4. ESLint Linting
```powershell
$nodeDir = Split-Path $env:CODEX_MCP_NODE_PATH; $env:PATH = "$nodeDir;$env:PATH"
pnpm --filter learner-web lint
# Result: eslint . --max-warnings 0 - Process exited with code 0 (clean, 0 warnings)
```

### 5. Production Build
```powershell
$nodeDir = Split-Path $env:CODEX_MCP_NODE_PATH; $env:PATH = "$nodeDir;$env:PATH"
pnpm --filter learner-web build
# Result: Compiled and generated all 25 application routes successfully (clean, exit 0)
```

---

## Guardrails & Non-Negotiable Compliance

- **No Unrelated Code Edits**:
  - Only `apps/learner-web` shell and sidebar files and focused tests were modified.
  - Zero Python files, database migrations, or knowledge/FTS code were edited.
  - Pre-existing dirty files in the worktree (`apps/admin-web/app/lib/dev-api-proxy.*`, `apps/learner-web/app/lib/dev-api-proxy.*`, `Authority_Closers_LMS_Learner_Journey_UX_Audit_FINAL.docx`) were preserved untouched.
- **Zero Git State Mutation**:
  - No `git commit`, `git push`, or deployments were executed.
- **Node 24 Enforcement**:
  - All test, typecheck, lint, and build commands were executed using the repository-mandated Node 24 runtime (`v24.19.0`).
