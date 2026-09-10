# Learner UI polish checkpoint — 2026-09-05

## Scope

- Worktree: `C:\Users\Suyash\.codex\worktrees\d2de\authority-closers-platform`
- Branch: `codex/local-staging-dev-bridge`
- Base HEAD at checkpoint start: `4aee7dd238136839236ed8dac81906467f65862b`
- Implementation lane: Antigravity CLI (`agy`) using `gemini-3.8-flash-high`, `--effort high`, and `--mode accept-edits`.
- No commit, merge, deploy, database, auth, API, or media-contract changes were made by the UI lane.

## Implemented

- `apps/learner-web/app/components/discover-runtime.tsx`
  - Added explicit retryable versus terminal catalog error presentation.
  - Kept error markup aligned with the canonical `surface-state` icon/body structure and modifier classes.
  - Added truthful first-page summary copy using the exact number of loaded programs.
  - Added neutral empty-state actions, catalog eyebrow, and accessible action labels.
  - Removed fabricated program ordering labels.
- `apps/learner-web/app/components/learning-runtime.tsx`
  - Added semantic Dashboard / My Learning breadcrumbs with `aria-current="page"`.
- `apps/learner-web/app/course-surfaces.css`
  - Added restrained card hover/focus motion, reduced-motion handling, responsive Discover/collection behavior, focus-visible affordances, dark-theme shadows, and an unclipped 2-by-2 mobile filter layout.
- `apps/learner-web/app/learner-next-slice.css`
  - Removed the duplicate floating Help trigger at bottom-navigation widths because Help & Support remains available in the mobile More sheet.
- `apps/learner-web/app/lib/direction-a-shell.test.ts`
  - Added the mobile Help de-duplication contract.
- `apps/learner-web/app/lib/learner-course-surfaces.test.ts`
  - Added coverage for catalog error classification/presentation/markup, summary scope/copy, breadcrumb semantics, and CSS contracts.

The founder-provided audit file `Authority_Closers_LMS_Learner_Journey_UX_Audit_FINAL.docx` remains untracked and untouched.

## Validation

- `pnpm --filter @ac/learner-web test` — pass (31 files, 474 tests).
- `pnpm --filter @ac/learner-web typecheck` — pass.
- `pnpm --filter @ac/learner-web lint` — pass (`--max-warnings 0`).
- Prettier check on all six changed learner files — pass.
- `pnpm --filter @ac/learner-web build` — pass (25 static pages generated).
- `git diff --check` — pass.

The UI lane's first check reported Node `v22.17.0`. The release orchestrator repeated the complete gate with the repository's configured Node 24 runtime before promotion; every check passed.

## Visual QA status

The release orchestrator found a stale tracked bridge process, stopped only the recorded bridge PIDs, and restored the bounded bridge at `learner.localhost:3100` and `admin.localhost:3101`. The unrelated application on port 3000 was not touched.

Chrome-only deterministic browser QA then exercised the production UI components with response-shaped fixtures at 1440 by 900 and 390 by 844. Assertions covered the loaded page heading and course card, semantic breadcrumb/current-page state, and zero horizontal document overflow. The first visual pass exposed two real mobile defects: the floating Help trigger covered course content/actions, and the Saved filter was clipped in the horizontal tab strip. Both were fixed and the four final images were recaptured and visually inspected:

- `screenshots/learner-ui-polish-2026-09-05/discover-desktop.png`
- `screenshots/learner-ui-polish-2026-09-05/discover-mobile.png`
- `screenshots/learner-ui-polish-2026-09-05/my-learning-desktop.png`
- `screenshots/learner-ui-polish-2026-09-05/my-learning-mobile.png`

These are local candidate captures with deterministic data, not claims of canonical learner state. Authenticated exact-release staging capture remains a post-deployment acceptance gate. The interactive Chrome profile also verified that the local unauthenticated Discover state renders the canonical sign-in recovery presentation. Its development-only hydration warning was attributable to extension-injected `bis_*` attributes and not present in the clean headless Chrome capture.
