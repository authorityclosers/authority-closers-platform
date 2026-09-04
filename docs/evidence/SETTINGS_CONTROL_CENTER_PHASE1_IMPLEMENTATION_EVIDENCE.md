# Settings control center — Phase 1 implementation evidence

Status: committed, bounded learner-web presentation slice. No new API,
account persistence, provider activation, or production deployment is included.

## Authority and scope

The source manifest and exact controlled-source fetch order are recorded in
[`source-manifest.csv`](../workflows/learner-product-v1/06-screen-family-v0.1-alpha/01-research-journeys/source-manifest.csv).
The implementation follows the local controlled interpretations in
[`SF-SET-001-settings.md`](../knowledge/v0.1-alpha/SF-SET-001-settings.md),
[`API-004-session-settings.md`](../knowledge/v0.1-alpha/API-004-session-settings.md),
[`JRN-04-profile-settings-appearance.md`](../knowledge/v0.1-alpha/JRN-04-profile-settings-appearance.md),
and the Clarity Grid design contract.

- The runtime vocabulary remains SET-01 through SET-05: verified account,
  appearance, learning setup, security/privacy, and session.
- The new Account, Setup & preferences, and Security & access headings are
  presentation-only index groups; they do not add capabilities or reorder the
  cards.
- Appearance remains browser-local presentation state. The scope note makes
  that boundary visible, allows for storage unavailability, and does not claim
  server persistence.
- Security/privacy explicitly states the first-slice boundary while retaining
  only the existing password-recovery and Terms/Privacy routes.

## UI implementation

- The settings index is grouped from the typed registry, keeps stable anchors,
  and adds SET numbers for faster scanning. Each group is a labeled native
  section with a heading for assistive-technology navigation.
- Offline/stale provenance is rendered as a direct ledger child with an
  explicit full-column placement, so it cannot be mistaken for a rail-only
  warning.
- Desktop uses a sticky, scrollable index rail; the content ledger gains more
  intentional spacing and existing theme density/shadow variables.
- The 761–950px medium layout collapses the appearance and motion grids before
  the two-column rail can create a horizontal overflow.
- Mobile uses readable card sizing, grouped two-column links (collapsing to one
  column at 360px), larger facts/actions, and a full-width session action.
- Advanced appearance controls remain available, but are arranged into a
  responsive grid with clearer grouping and touch targets.

Changed files:

- `apps/learner-web/app/components/settings-clarity.module.css`
- `apps/learner-web/app/components/settings-runtime.test.tsx`
- `apps/learner-web/app/components/settings-runtime.tsx`
- `apps/learner-web/app/components/theme-control.tsx`
- `apps/learner-web/app/lib/settings-registry.test.ts`
- `apps/learner-web/app/lib/settings-registry.ts`

The isolated worktree is
`D:\Projects\authority-closers-platform-settings-control-center-phase1` on
`codex/settings-control-center-phase1`, rebased onto `origin/main` at
`14f0c57818c600ddc5be5fede17ea8ebea202815`. This slice does not modify
course, avatar, learner-api, profile-runtime, or offline-cache files.

## Verification

- `pnpm --filter @ac/learner-web test` — PASS, 28 files / 380 tests after
  rebasing onto the course-first and avatar/profile mainline.
- `pnpm --filter @ac/learner-web typecheck` — PASS.
- `pnpm --filter @ac/learner-web lint` — PASS.
- `pnpm --filter @ac/learner-web build` — PASS. The available runtime reports
  the repository's existing Node `>=24 <25` engine warning under Node 22.
- `pnpm exec prettier --check` on the six changed source/test files and this
  evidence record — PASS.
- `git diff --check` — PASS.

The tests cover registry grouping, stable SET ordering, native group labels,
the full-span offline notice, the 761–950px overflow guard, visible
browser-local scope copy, honest first-slice security copy, and five numbered
index links.
Browser visual QA and staging/live evidence were not run because the task
explicitly prohibited Playwright and alternate-browser use.
