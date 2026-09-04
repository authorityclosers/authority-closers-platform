# Learner sidebar consolidation evidence — 2026-09-04

## Outcome

The learner desktop shell now has one persistent sidebar control that expands and
collapses the rail without hiding nested navigation icons. The collapsed state
uses the compact Authority Closers mark, hides every navigation label (including
Help), keeps the notification icon visible, and persists across reloads. The
duplicate sidebar identity pill was removed because the header account control
remains the single identity surface in the selected desktop composition.

The change also makes protected learner navigation explicitly opt out of
automatic Next.js prefetch. This is the smallest safe treatment recommended by
`AC-PERF-001`; it does not introduce a new cache or speculative scheduler.

## Visual authority and bounded scope

Compared against:

- `docs/workflows/learner-product-v1/03-visual-exploration/selection.md`
- `docs/workflows/learner-product-v1/03-visual-exploration/direction-a-command-center-desktop.png`
- `docs/workflows/learner-product-v1/03-visual-exploration/founder-selected-dashboard-desktop-rich-v1.png`

The implementation keeps the selected warm-white/navy/cobalt Direction A shell,
desktop rail, compact utility header, five primary workspace routes, and mobile
bottom navigation. It does not invent course, media, learner, progress, or tenant
state.

The old Antigravity sidebar, Learn/Discover, and player worktrees were inspected
before this repair. Their relevant product slices are already represented by
merged PRs, while wholesale merges would conflict with or delete newer avatar,
settings, notifications, media, progress, and QA work. No stale worktree was
merged.

## Defects closed

- Replaced the broad collapsed selector that hid every nested `span` and could
  suppress the notification badge/icon wrapper with an explicit
  `.learner-nav__label` contract.
- Moved the only desktop collapse control from the utility header to the sidebar
  footer and restored the visible Expand/Collapse label.
- Replaced the collapsed 11 px wordmark treatment with the existing `BrandMark`.
- Added safe persisted state using `useSyncExternalStore`, local storage, a
  same-document event, and an in-memory fallback for storage-restricted contexts.
- Removed dead prior-generation collapse and sidebar identity selectors from the
  learner CSS and reduced-motion theme selector list.
- Restored the responsive multi-program grid and capped only its lone card at
  the selected compact-card width, avoiding both a stretched one-course banner
  and under-filled multi-course catalogs on desktop.
- Retained `aria-label`, `aria-expanded`, `aria-controls`, link titles, keyboard
  focus styling, and the existing mobile shell.

## Browser review

Chrome was used against the local production code path with only the public
staging API origin configured; no staging cookies or credentials were forwarded.
The protected `/home` data request therefore returned the expected explicit
“Learner access is unavailable” state while leaving the shell reviewable.

Observed at the normal desktop viewport:

- expanded rail: full wordmark, all labels, five workspace routes, account
  routes, and the single Collapse control were visible;
- collapsed rail: 72 px rail, compact brand mark, icons only, visible notification
  icon, hidden Help label, and one Expand control;
- interaction: the control changed `aria-expanded` and the rail width in both
  directions;
- persistence: after reload, the previously selected collapsed state returned.

The Next.js development issue badge overlapped the bottom-left control in local
screenshots. That badge is development-only and is not part of the production
bundle. Production-build validation below passed.

Authenticated content-state review and exact staging screenshots remain release
checks after this branch is merged and deployed; they are not claimed here.

## Validation

Run from the branch worktree:

```text
pnpm --filter @ac/learner-web test
29 test files passed; 403 tests passed

pnpm --filter @ac/learner-web lint
passed with zero warnings

pnpm --filter @ac/learner-web typecheck
passed

pnpm --filter @ac/learner-web build
compiled and generated all 25 application routes

pnpm exec prettier --check <changed TypeScript and CSS files>
passed

git diff --check
passed
```

The local host has Node.js 22.17.0 and emitted the repository's expected engine
warning because the package requests Node.js 24. CI must repeat validation on the
repository runtime before merge.
