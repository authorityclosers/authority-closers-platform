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
