# Preserved candidate evidence from edb6ea903a4374f3286f333affea12bf795ced40

Original path: `docs/evidence/20260910_COACH_WORKSPACE.md`. This separately preserved candidate record does not replace the existing main record or establish acceptance of the reconciled release. The original candidate content follows unchanged.

---

# Coach workspace candidate — 10 September 2026

Status: local implementation, not production acceptance. Release artifact `7bdd069d4bf00561edcab90b1679666205708185` does not contain this candidate.

## Implemented

- Persistent Coach layout with Dashboard, Courses, Publication and Settings; desktop sidebar, mobile navigation and course breadcrumbs.
- Dashboard counts and next course links from the canonical scoped Studio list. Bounded-list disclosure; no invented revenue, learners or learning progress.
- Publication queue from canonical readiness with search, status filters, plain-language checks and links into the existing course editor. No blind publication shortcut.
- Settings with light/dark/system and reduced motion, browser-local persistence and truthful storage-failure feedback. Existing verified identity and assigned-course versus academy-wide access labels. Normal sign-out with failure recovery.
- Shared palette and illustration primitives. No new brand, tenant identity grant or permission bypass.
- Reviewer found stale persistent-session and failure-classification gaps. Provider now supports route and opt-in focus/visibility revalidation, hides/inerts private work while checking, preserves same-session input and resets confirmed identity changes. Native dialogs are suspended during a check so they cannot block reconnect.
- Studio responses from another tenant fail into an error boundary instead of a blank page. API session HTTP 401/403 remains denied; network/503 is retryable.

## Verification

- Coach TypeScript passed after route/settings implementation and revalidation wiring.
- Coach component suite: 12 passing tests covering data, empty/bounded states, wrong-tenant response, late session response, retry, queue filters, scoped access, navigation, theme persistence/storage failure and sign-out failure.
- Final Admin regression suite: 484 passing tests across 20 files, including 16 provider-specific tests and native-dialog suspension/reconnect. Final Coach typecheck, 12 Coach component tests, Coach ESLint and whitespace checks passed.
- Reviewer source inspection found and corrected the issues above; final regression rerun is recorded in task command output.
- Browser acceptance is **blocked**, not passed: the existing local Coach process returns HTTP 500 with Windows `UNKNOWN lstat 'C:\\'`. Existing Admin process also needs local runtime repair. No production deployment or native-device claim follows from unit tests.
- Browser attempt evidence: `.tmp/local-platform/new/coach-acceptance-20260909/coach-acceptance.json`. HTTP 500 captures are failure evidence, not new UI acceptance.

## Antigravity experiment (separate)

User requested one independent UI concept via `agy`. Isolated brief and raw generated single-file prototype are in `.tmp/antigravity-studio-experiment/`. No generated code was imported into product routes. It runs on loopback port 3205 with sample data only and no external dependencies/network calls.

Root inspected actual 1440px dashboard/editor and 390px editor screenshots. Useful outline/editor separation, but the output remains a generic dense admin interface, with a cramped mobile toolbar and editing controls below a long outline. It also invents capability statements (such as transcript parsing being in staging) that must not be adopted. This is exploration, not a release candidate.

## Remaining acceptance

Restore the managed local Coach runtime without elevating application processes; rerun desktop/mobile/light/dark/keyboard acceptance on the real routes. Continue actual course/upload workflows and tenant-configurable branding controls separately. Package only reviewed, accepted changes; do not describe this local candidate as already live.

## Root release-candidate addendum

The earlier localhost HTTP500 block above was repaired; retain that capture only as historical failure evidence. The clean migration-free release candidate is `783da9838179ee32f0481d9bae9a8b1b30a95ec4`, exact parent `7bdd069d4bf00561edcab90b1679666205708185`, in the separate `coach-workspace-staging` worktree. Its manifest contains 25 files and excludes unfinished course creation, media, worker and schema changes.

Independent review identified and fixed: (1) unbounded session checks, now ten-second abortable checks with retry and preservation of same-session private input; (2) recommendation copy that could imply write access for a read-only course, now requiring both selected-tenant content and canonical catalogue-write capability; and (3) Coach sign-in landing on the course list rather than Dashboard. The final independent range review approved the candidate with no Critical, Important or Minor findings. Root mirrored the narrow fixes into the integrated local tree while preserving its separate course-creation work.

Final exact-candidate normal-auth browser proof: `.tmp/local-platform/coach-isolated-acceptance-20260910-025005-857209/proof.json`. HEAD and clean worktree were checked before and after. Coach sign-in landed at `/studio`. Sixteen route/theme combinations across Dashboard, Courses, Publication and Settings at 1440/390 light/dark passed with zero horizontal overflow or offscreen actions. A labelled GET-only delayed `/v1/me` fixture showed recoverable Reconnect and then recovered. The root managed Coach runtime was restored afterward and returned HTTP200. Earlier `e57c596` proof is predecessor-only because a concurrent source fix occurred during that run.

Clean candidate checks: Coach 14 tests; Admin full 433 tests and focused session/API/login 124 tests; both typechecks, lints and sequential production builds passed under Node24/768MiB. One initial Windows OS1450 resource failure was followed by a successful isolated Coach build. Root integrated-tree focused checks also passed Coach14 and Admin124. This does not certify the unfinished integrated media/course-creation delta.

Root authorized only exact-branch push and one `application.yml` validation/packaging dispatch for the final SHA. Deployment and production acceptance are not implied by this authorization or browser proof.

## Verified staging promotion

After GitHub Actions run `34406701015` completed all validation, capacity simulation and image-packaging jobs successfully, root deployed exact SHA `783da9838179ee32f0481d9bae9a8b1b30a95ec4` through the reviewed `Deploy-Staging.ps1 -TargetEnvironment staging` controller. It exited zero, proving the digest-bound archive, canonical installer, Learner/Coach/API routes, protected Admin Access, disabled API docs, static/PWA assets, same-host sign-in/OAuth start, legacy redirects and unchanged WordPress apex/www. A separate SSH read resolved `current-staging` to that exact release directory. This is staging acceptance of the narrow Coach/session candidate, not production launch or deployment of the separate local community/media work. A real Google login/callback and broader course/media workflows are not claimed by the OAuth-start smoke.
