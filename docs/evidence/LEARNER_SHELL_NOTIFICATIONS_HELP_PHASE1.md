# Learner shell notifications and help — Phase 1 evidence

Status: bounded implementation evidence (not deployed)
Date: 2026-09-04
Branch: `codex/shell-notifications-help-phase1`
Base: `origin/main` at `b5348cc`

## Scope

This slice polishes the authenticated learner shell surfaces that are already
in the first-slice route contract:

- The profile menu now presents the `/v1/me` identity (display name and email)
  with the existing provider-owned avatar URL when available, initials when it
  is absent, and an initials fallback after an avatar delivery failure. It
  does not infer role, tenant, or authorization from presentation data.
- The bell surface is a reusable popover that mirrors the notifications route's
  `source_not_connected` state and links to `/notifications`. It does not
  invent notification rows, unread counts, read mutations, or delivery history.
- The help panel is a premium support shell around the existing learner support
  `mailto:` capability. It explicitly states that in-app chat is not connected;
  it does not imply a live agent, connected LLM, or fabricated conversation.
- Focus restoration, Escape/outside-click dismissal, 44px action targets,
  responsive mobile placement, theme tokens, and reduced-motion handling are
  retained or made explicit for these surfaces. Theme preference feedback
  remains local to the theme control; shell status is not surfaced as a debug
  toast.
- The support trigger stays above the fixed bottom navigation through the
  1023px mobile/tablet breakpoint, and the brand mark cutout uses the action
  tile token so light/dark and accent variants remain coherent.
- Email support activation closes through the shared focus-restoring helper;
  account-menu Tab closes without preventing native document order or moving
  focus back to the trigger, while Escape and outside-click still restore it.

## Evidence links

- Controlled shell/navigation and state contracts: `docs/contracts/V0_1_ROUTE_SCREEN_CONTRACTS.md`
- Authenticated route authorization: `docs/contracts/G1_ROUTE_AUTHORIZATION.md`
- Authorization matrix: `docs/security/AUTHORIZATION_MATRIX.md`
- Learner experience source ledger: `docs/knowledge/v0.1-alpha/SRC-020-product-experience.md`
- State interface assurance: `docs/knowledge/v0.1-alpha/SRC-030-state-interface-assurance.md`
- Trust and operations boundaries: `docs/knowledge/v0.1-alpha/SRC-050-trust-operations.md`
- UX acceptance reference: `docs/workflows/learner-product-v1/06-screen-family-v0.1-alpha/05-handoff-qa/qa-release-checklist.md`

## Changed implementation

- `apps/learner-web/app/components/site-shell.tsx`
- `apps/learner-web/app/components/notifications-runtime.tsx`
- `apps/learner-web/app/lib/notifications.ts`
- `apps/learner-web/app/learner-next-slice.css`
- `apps/learner-web/app/theme.css`
- `apps/learner-web/app/components/theme-control.tsx`

Focused contract tests cover the shared unavailable notification copy, popover
relationship, owned notification links, avatar fallback/identity wiring, and
absence of shell debug-toast wiring.

## Validation

Run from the isolated worktree:

```text
pnpm --filter @ac/learner-web exec vitest run app/lib/direction-a-shell.test.ts app/components/notifications-runtime.test.tsx app/components/theme-control.test.tsx
pnpm --filter @ac/learner-web typecheck
pnpm --filter @ac/learner-web lint
pnpm --filter @ac/learner-web test
pnpm --filter @ac/learner-web build
git diff --check
```

Observed on the rebased worktree (`b5348cc` plus the uncommitted slice):

- Focused shell/notification/theme tests: 3 files, 69 tests passed.
- Learner package suite: 28 files, 381 tests passed.
- TypeScript, ESLint, production build, and `git diff --check`: passed.
- The package emitted the repository's existing Node engine warning because the
  validation host is running Node 22 while the workspace declares Node 24.

No browser automation, commit, push, deployment, or provider activation was
performed for this evidence slice.
