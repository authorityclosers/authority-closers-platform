# Alpha sidebar navigation feedback — 2026-09-07

## Scope and result

The sidebar set a local pending flag on every click and never reset it. A
persistent shell could therefore keep old links dimmed after navigation or
show pending feedback for a click that did not navigate.

`SidebarNavItem` now reads the installed Next 16.2.11 `useLinkStatus` hook from
a child of `Link`. Next owns the pending lifetime; the item keeps no duplicate
navigation state. The existing inner span exposes `is-pending`, `aria-busy`,
and an accessible opening message only while that link is pending. The shell
stylesheet consumes that descendant state in the parallel consolidation edit.

Internal navigation callbacks and the existing UI event run through Link's
`onNavigate`. Exact-current-URL clicks are no-ops; an active section link still
works from a different child URL. Modified clicks keep browser behavior.
External links use a native anchor and never display SPA pending feedback.
Disabled, current, hidden, collapsed, and nested item semantics are retained.
`prefetch={false}` remains on every internal link.

The document-level dirty-navigation guard is unchanged. Its canceled click
does not reach the Link callback or emit navigation feedback; a later confirmed
retry can navigate. No auth, membership, progress, media, or access authority
was changed. This is bounded UX-G01/02/04/09 work within the controlled-source
review performed for the Alpha consolidation.

## Verification

Runtime: Node 24.19.0, pnpm 11.19.0, Vitest 4.1.11.

- 13 new DOM behavior tests pass: pending start/completion without remount,
  repeat navigation, supersession, exact-current-URL no-op, active section
  navigation from a child, five modified clicks, external link, disabled and
  hidden entries, and dirty cancellation followed by confirmed retry.
- 85 tests pass across `sidebar-nav-item.test.tsx`,
  `learner-sidebar.test.tsx`, `learner-sidebar.dom.test.tsx`, and
  `local-drafts.test.ts`.
- Learner TypeScript check passes.
- Focused ESLint and Prettier checks pass.

The new tests mount the real sidebar component and use the real document dirty
guard. A test router stand-in exposes the documented per-Link pending and
accepted-navigation contract so completion and supersession are deterministic.
This is component evidence, not a claim of browser, live staging, or production
acceptance. The exact-release browser check must still navigate between learner
routes without remounting the shell, cancel a dirty-form exit, confirm a retry,
and verify that no stale pending indicator remains.

Commands (run with Node 24 on PATH):

```powershell
pnpm --filter @ac/learner-web exec vitest run app/components/learner-sidebar/sidebar-nav-item.test.tsx app/components/learner-sidebar/learner-sidebar.test.tsx app/components/learner-sidebar/learner-sidebar.dom.test.tsx app/lib/local-drafts.test.ts
pnpm --filter @ac/learner-web exec eslint app/components/learner-sidebar/sidebar-nav-item.tsx app/components/learner-sidebar/sidebar-nav-item.test.tsx --max-warnings 0
pnpm --filter @ac/learner-web typecheck
pnpm exec prettier --check apps/learner-web/app/components/learner-sidebar/sidebar-nav-item.tsx apps/learner-web/app/components/learner-sidebar/sidebar-nav-item.test.tsx docs/evidence/20260907_ALPHA_SIDEBAR_NAVIGATION.md
```

## API evidence

- Inspected installed `next/dist/client/app-dir/link.js` and `link.d.ts`:
  per-Link optimistic status, descendant context, browser/cancellation filtering,
  and `onNavigate` support.
- [Next useLinkStatus documentation](https://nextjs.org/docs/app/api-reference/functions/use-link-status)
  and [Link API documentation](https://nextjs.org/docs/app/api-reference/components/link),
  read 2026-09-07. The installed version remains the implementation reference;
  no framework dependency was upgraded.

No staging/production changes, credential operations, commits, or deployments
were performed for this fix.

## Dated addendum — 2026-09-09 — mobile Arcade navigation

The mobile navigation follow-up changed `apps/learner-web/app/components/learner-sidebar/mobile-navigation.tsx`,
`apps/learner-web/app/components/site-shell.tsx`, and
`apps/learner-web/app/lib/routes.ts`. Focused coverage in
`learner-sidebar.dom.test.tsx`, `practice-availability.test.tsx`, and
`local-drafts.test.ts` passed **80 tests**. Full learner TypeScript and scoped
ESLint checks also passed with the 768MB memory limit.

Read-only authenticated local browser verification at 320px light and 390px
light/dark showed Arcade as the capability-gated third bottom tab, Discover
under More, and `/practice?set=gaps` with zero chrome. Five touch targets were
at least 44px. The run observed zero blocked requests or mutations. Its
screenshots and proof remain temporary files under `.tmp` and were not staged.
This is local implementation/QA evidence only; it does not establish staging
or production acceptance.

## Dated addendum — 2026-09-09 — Admin mobile navigation overflow

The late Clarity `@media (max-width: 1180px)` rule in the shared operations
stylesheet now keeps the Admin primary navigation as a two-column grid with
visible overflow, 44px link targets, shrink-safe icons, and wrapping labels.
Desktop navigation and the Coach shell were not changed. The focused
`operations-theme.test.ts` regression and the existing `admin-ui.test.tsx`
layout suite passed together: **2 files / 26 tests** (the Admin UI file retains
35+ layout assertions).

The first browser attempt used the existing Playwright CDP helper with
`--baseline` and timed out at the 180-second CDP attach; no baseline was
captured. The same existing helper was then rerun without `--baseline`; its
Playwright Chromium CDP connection and new page succeeded, with exact
Admin-origin GET/HEAD-only interception applied before navigation. The command
was:

```powershell
python .tmp/local-platform/verify-admin-mobile-nav.py
```

All **8 local-dev cases** (320/390/768/1440px × light/dark) passed: four
primary links were visible, targets measured at least 44px, the long
`Learning operations` label wrapped at narrow widths, navigation and document
horizontal overflow were absent, and keyboard focus assertions passed. No
requests were blocked and the owned tab was closed. Proof and captures remain
temporary under
`.tmp/local-platform/admin-nav-after-ut3l7ogb/` and were not staged. This is
local implementation/browser evidence only; it does not establish staging or
production acceptance.
