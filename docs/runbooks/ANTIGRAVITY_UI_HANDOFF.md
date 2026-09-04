# Antigravity UI development and release handoff

Status: active local development lane; never an automatic deployment source.

## Canonical UI worktree

Use this existing worktree for learner and admin UI/UX changes:

```text
C:\Users\Suyash\.codex\worktrees\d2de\authority-closers-platform
```

The shared lane branch is `codex/local-staging-dev-bridge`. Point Antigravity
at the worktree root. Learner UI belongs in `apps/learner-web`; admin UI belongs
in `apps/admin-web`. Do not create new AC product work in any Naya repository or
in the archived/handoff repositories under `D:\Projects`.

This is the single persistent Antigravity implementation lane. Do not create an
additional UI worktree or parallel editing branch by default. If another task
needs this checkout, sequence ownership and handoff instead of allowing
concurrent writers.

The branch includes the secure localhost-to-staging bridge so UI work can use
realistic staging identity, tenant, catalog, and progress behavior. It does not
authorize production data, direct databases, provider activation, or autonomous
deployment.

## Learner brand hierarchy

The founder-confirmed learner-facing product name is `Closers Academy`, with
`by Authority Closers` as the tenant attribution. Authority Closers is the
tenant using this LMS; it is not the generic LMS product name. The underlying
multi-tenant LMS has no approved name yet. Do not invent one or encode Authority
Closers as a platform-global brand. Wordmarks, accessible names, navigation, and
future Academy Studio surfaces must preserve this hierarchy, including
collapsed-sidebar and mobile treatments.

## Daily workflow

1. From the worktree root, inspect `git status --short` and preserve every
   existing user edit. Do not reset, checkout over, or silently discard files.
2. Start the bridge with `pnpm dev:staging`. Work at
   `http://localhost:3000` and `http://localhost:3001` only.
3. Keep changes inside the named slice. Do not broaden API allowlists merely to
   make an unfinished screen look connected; record gated or absent capability
   states truthfully.
4. Run the focused app tests while editing. Before handoff, run the complete
   validation and visual QA below.
5. Stop with `pnpm dev:staging:down` when the session ends. This drops the
   ephemeral local session mappings; logs remain ignored under `.tmp`.

Avoid concurrent edits to the same file. Before another tool or task edits an
auth, bridge, root layout, route, or shared stylesheet file, coordinate who owns
that file and finish or commit the first change.

## Antigravity CLI orchestration

The Antigravity desktop application and `agy` CLI are separate installations.
Verify `Get-Command agy` before starting a CLI run. If the CLI is absent, use
Google's official Windows installer from
`https://www.antigravity.google/docs/cli/install/`; do not improvise a binary or
put an API key in this repository.

Codex remains the orchestrator. Each `agy` prompt must name this worktree,
identify the exact screens and files in scope, require reading `AGENTS.md`,
preserve the reported dirty state, prohibit branch/commit/deploy/database work,
and request a concise changed-file summary. Prefer one bounded headless prompt
per checkpoint, for example:

```powershell
agy -p "Work only in the current Authority Closers worktree. Read AGENTS.md, report git status, and implement only the supplied UI checkpoint. Preserve existing edits. Do not commit, deploy, change auth/API contracts, or touch databases. Return changed files and unresolved questions." --model gemini-3.8-flash-high --output-format json --effort high --print-timeout 15m
```

Do not pass `--dangerously-skip-permissions`. Keep Antigravity's permissions
scoped to workspace reads/writes; Codex runs and assesses the required shell
validation separately. Never place staging passwords, cookies, Access JWTs,
provider credentials, or production data in an Antigravity prompt, output, or
workspace file. After every run, Codex inspects `git status` and the full diff
before allowing another checkpoint.

## Sync and rebase procedure

Never rebase a dirty worktree. First inspect and deliberately commit the
intended UI changes on this branch; if ownership or intent is unclear, stop and
coordinate instead of stashing or deleting them.

```powershell
pnpm dev:staging:down
git status --short
git fetch origin
git rebase origin/main
git status --short
```

Resolve conflicts by preserving both the current controlled contract and the
intended UI change. Pay particular attention to `apps/learner-web`,
`apps/admin-web`, environment contracts, ADRs, and release evidence. Never
resolve by accepting an entire side without reviewing the semantic difference.
After the rebase, rerun the full checks and the bridge health workflow.

If `main` changed auth/session, tenancy, route, audit, provider, payment, or
deployment behavior, stop the release handoff until the corresponding
controlled sources and gates have been reconciled. A P0 blocks its capability,
not unrelated UI work.

## Required validation

Use Node 24 and pnpm 11. At minimum, run:

```powershell
pnpm --filter @ac/learner-web lint
pnpm --filter @ac/learner-web typecheck
pnpm --filter @ac/learner-web test
pnpm --filter @ac/learner-web build
pnpm --filter @ac/admin-web lint
pnpm --filter @ac/admin-web typecheck
pnpm --filter @ac/admin-web test
pnpm --filter @ac/admin-web build
uv run pytest -q tests/infra/test_local_staging_bridge.py
pnpm dev:staging
```

Confirm learner public catalog health, learner password login and protected
reads, admin Access transport health, admin password login and verified tenant
context, logout, and restart-stale-cookie recovery. Do not put credentials in
test output or evidence.

Perform responsive visual QA at 360×800, 768×1024, and 1440×900 for every
changed screen. Exercise default, loading, empty, validation, denied, expired,
retryable failure, and success states that apply. Check keyboard order, visible
focus, headings/landmarks, labels, touch targets, contrast, overflow, content
wrapping, and reduced-motion behavior. Record which routes/states/viewports
were actually checked; do not claim visual QA from source inspection alone.

## Release-candidate handoff

This branch must not auto-deploy. For every staging candidate:

1. Reconcile this branch against current `origin/main` using the procedure
   above.
2. Identify the intended UI commits explicitly. Do not silently omit or absorb
   unrelated local edits.
3. Run the relevant learner/admin checks, responsive visual QA, bridge health,
   and any slice-specific API/security tests.
4. Record the exact candidate commit with `git rev-parse HEAD` in the evidence
   document and release task.
5. Coordinate any conflict or drift with the main release task before creating
   the candidate.
6. Promote only through the existing staging and production gates. Production
   must reuse the exact staging-proven artifact and source SHA; do not rebuild,
   patch, or manually mutate production state during promotion.

The release task owns merge, staging deployment, verification, and production
promotion. This UI lane owns intentional UI commits and their evidence. A
successful local bridge check is implementation evidence, not deployment
approval.

## Next release target: approved lesson video

The next product release after this bridge is one real, approved lesson video
playable end-to-end on staging. Keep its player/UI work in this lane so it can
be reconciled with ongoing learner changes, but do not turn the bridge into a
media-provider activation path. Preserve the existing media contract,
activity-to-media immutability, authorization, provenance, consent/retention,
range/telemetry, and professional/governance gates—including AC-GOV-AUD-001—
until the release task supplies the required approvals and staging artifact.

Before that slice is handed off, explicitly list the player/activity screens,
media bindings, tests, viewport/browser evidence, approved asset identity,
provider and provenance gates, candidate commit, staging artifact, and rollback
identity. Reconcile those commits into the current UI lane rather than opening
a parallel Antigravity worktree or dropping other UI changes.
