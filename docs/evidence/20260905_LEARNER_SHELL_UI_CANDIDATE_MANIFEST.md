# Learner shell UI candidate manifest

- Evidence date: 2026-09-05
- Worktree: `C:\Users\Suyash\.codex\worktrees\d2de\authority-closers-platform`
- Branch: `codex/local-staging-dev-bridge`
- Current base commit: `a0214f9445595e45dccbf96f08de232e6cb62aff`
- Candidate commit: `79041eca2941082e7db1ab73c603fe728c39f7a5` (`feat(learner): refine shell sidebar and command palette UI`), pushed to `origin/codex/local-staging-dev-bridge`.
- Release target under observation: `1fd26f0eabd70c2ea4f2f0f440c8e1179a8dac46` (not claimed as live here).
- Deployment: none.

## Scope inventory

### Learner shell and interaction changes

- `apps/learner-web/app/components/site-shell.tsx`
  - Removes the redundant header context label.
  - Keeps centered header search and notification/account controls.
  - Uses the explicit `Closers Academy` / `by Authority Closers` tenant hierarchy.
  - Places the collapse control as a hidden-at-rest overlay over the brand region.
  - Connects sidebar/header search and `Ctrl`/`Cmd` + `K` to the command palette.
  - Keeps mobile bottom navigation and one `MobileMoreSheet` owner.
- `apps/learner-web/app/learner-next-slice.css`
  - Theme-synced light and dark sidebar tokens.
  - `280px` expanded rail, `76px` collapsed rail, `76px` aligned header.
  - Hover/focus-only collapse affordance, portal tooltip layering, transparent header, and responsive states.
- `apps/learner-web/app/components/learner-sidebar/learner-sidebar.test.tsx`
  - Covers geometry, theme synchronization, overlay behavior, mark cutout, command palette, and copy contracts.
- `apps/learner-web/app/components/learner-sidebar/learner-sidebar.dom.test.tsx`
  - Covers modal ownership, focus restoration, and body-portal tooltip behavior.

### Local staging bridge repair

- `apps/learner-web/app/lib/dev-api-proxy.ts` and `.test.ts`
- `apps/admin-web/app/lib/dev-api-proxy.ts` and `.test.ts`
  - Accept the Next.js loopback URL only when the direct `Host` resolves to the configured virtual localhost origin.
  - Require forwarded headers to agree rather than trusting them alone.
  - Preserve strict unsafe-method `Origin` checks and reject hostile non-loopback requests.

## Validation inventory

- Learner suite: 31 files, 469 tests passed after candidate preparation.
- Learner typecheck: passed.
- Learner ESLint: passed with zero warnings.
- Learner production build: passed across 25 routes.
- Focused learner bridge suite: 36 tests passed.
- Focused admin bridge suite: 54 tests passed.
- Local staging bridge infrastructure suite: 7 tests passed.
- `git diff --check`: clean.
- Runtime health: `http://learner.localhost:3000/v1/programs?limit=1` returned HTTP 200 with `X-AC-Dev-Data-Mode: staging-public-catalog`; `http://admin.localhost:3001/v1/dev-bridge/health` returned `status: ok`, `transport: connected`.

## Chrome screenshot checklist

Chrome-only checks use the existing Chrome profile and the local virtual-host origins. No credentials were entered and no third-party form was submitted.

| Surface/state | Exact route | Expected identity/state | Evidence | Status |
| --- | --- | --- | --- | --- |
| Learner shell, expanded light, signed-out boundary | `http://learner.localhost:3000/home` | Closers Academy / by Authority Closers; light rail; transparent header; sign-in boundary is honest because the local session is absent | Live Chrome tab `436228229`, inline capture in task | Passed |
| Learner shell, collapsed light | `http://learner.localhost:3000/home` | `76px` icon rail; no labels at rest; content offset follows rail | Live Chrome interaction + inline capture in task | Passed |
| Collapsed focused navigation tooltip | `http://learner.localhost:3000/home` | Dashboard tooltip is body-level and overlays content without clipping | Live Chrome focus/capture; AX tree exposed `container Dashboard` | Passed |
| Command palette via sidebar search | `http://learner.localhost:3000/home` | Functional combobox, grounded learner routes, selected Dashboard | Live Chrome AX tree; dialog `learner-command-palette` | Passed |
| Command palette via `Ctrl+K` and Escape | `http://learner.localhost:3000/home` | Opens from keyboard, Escape closes, focus returns to invoking search control | Live Chrome keyboard interaction + AX focus state | Passed |
| Learner login desktop | `http://learner.localhost:3000/login` | Stable light auth form; no offline fallback or reload loop | `docs/evidence/screenshots/local-staging-bridge/learner-login-mobile.png` is the durable local asset; desktop verified live in Chrome | Passed |
| Learner login mobile | `http://learner.localhost:3000/login` | Responsive auth form with policy links and staging boundary | `docs/evidence/screenshots/local-staging-bridge/learner-login-mobile.png` | Passed |
| Admin login desktop | `http://admin.localhost:3001/login` | Development-only admin bridge boundary; no credential forwarding to browser | `docs/evidence/screenshots/local-staging-bridge/admin-login-desktop.png` | Passed |
| Admin overview/catalog responsive states | admin local routes | Existing admin design system remains unchanged by this learner-shell slice | Existing v0.1 local screenshot pack; fresh Chrome capture pending | Not in this slice |

The Chrome extension in the selected profile adds `bis_*` attributes before React hydration. Chrome reports the resulting React hydration mismatch as a dev-console error; the mismatch is extension instrumentation, not an application-rendered attribute or route failure. The live DOM, route behavior, bridge health, and interaction checks remained correct. This environment note is not treated as a release defect.

## Release and reconciliation gates

- Do not claim exact-SHA staging evidence until the release owner confirms `1fd26f0eabd70c2ea4f2f0f440c8e1179a8dac46` is live.
- Do not upload or publish screenshots before that confirmation.
- After confirmation, recapture the learner shell at the exact staging route and authenticated identity, plus the matching admin route; preserve both desktop and mobile captures as real files.
- Reconcile only the listed UI/bridge files into the release branch. Preserve the user-provided audit DOCX and any unrelated knowledge/database work.

final result: candidate committed and pushed; exact-staging visual evidence pending release-owner confirmation
