# Authority Closers continuation handoff — 2026-09-02

## Purpose

Continue the current Authority Closers platform/UI production work in a fresh Codex task without discarding or resetting the dirty worktree. The current live UI is explicitly not final. The immediate target is a premium, light-default learner application foundation that can be tested locally against safe staging/VPS data, works usefully when offline, and is deployed to staging only after exact-SHA validation and visual QA.

## Mandatory execution policy

- Use GPT-5.6 Sol as the orchestration model.
- Delegate bounded coding/review tasks only to GPT-5.6 Luna at `xhigh` reasoning effort. Never use `medium`. The user explicitly corrected this.
- Preserve all current uncommitted changes and `.artifacts`; do not reset or overwrite unrelated user work.
- Read repository `AGENTS.md` and controlled documentation before changing protected semantics.
- Every code change must leave tests and implementation evidence.
- Use Chrome only for browser/design QA; do not substitute Playwright unless the user explicitly approves it.
- Match the supplied reference screenshots through same-viewport reference/prototype comparison, not by visual memory.

## Current branch and repository state

- Repository: `D:\Projects\authority-closers-platform`
- Branch: `codex/g1-free-course-foundation`
- Baseline/current HEAD before this slice: `514b9f449ed8f3d17ee4143b6b0d126e443f5fd7`
- The worktree is intentionally dirty. Inspect it as the source of truth.
- The earlier Antigravity terminal handle and the earlier Luna subagent handle are no longer available; do not assume their jobs completed. Their edits are present in the shared worktree and must be reviewed and tested.

## User-facing product requirements

- Premium, serious, light-default UI with an authentic application feel.
- Distinct Dashboard/Home and My Learning.
- Desktop sidebar and header with search, notifications, profile menu, and clear information architecture.
- Purpose-built mobile navigation: Home, Learning, Discover, Progress, More.
- Real routes: `/home`, `/learning`, `/discover`, `/progress`, `/notifications`, `/profile`, `/settings`.
- Meaningful profile/settings foundation; avatar mutation is outside the current bounded slice unless controlled docs authorize it.
- Faster shell-retaining navigation with route-shaped skeletons, request dedupe, and cancellation.
- Provider-neutral media contracts that use a VPS origin now and can migrate to a CDN/provider later without rewriting product flows.
- Click-first/low-typing activity families and gamification are future slices; do not fake canonical scoring or rewards.
- Never fabricate learner metrics, courses, schedules, notifications, progress, or commerce state.

## Exact visual references

- Desktop: `C:\Users\Suyash\AppData\Local\Temp\codex-clipboard-3d6b4fee-ec2e-44b1-b32a-cbfc53700779.png`
- Mobile: `C:\Users\Suyash\AppData\Local\Temp\codex-clipboard-23f15b5b-859b-420a-82cc-33cbcec86346.png`
- Desktop alternate: `C:\Users\Suyash\AppData\Local\Temp\codex-clipboard-bf731b20-07bd-4429-9d57-1b48a5229aab.png`

Selected workflow/design documentation is under `docs/workflows/learner-product-v1/`, especially:

- `03-visual-exploration/selection.md`
- `04-ai-context/implementation-context.json`
- `02-ux-state-spec/route-state-matrix.csv`
- `05-handoff-qa/release-checklist.md`

## Implemented or partially implemented in the dirty worktree

### Learner application shell and route family

New/changed components and routes include the Dashboard, Learning, Discover, Progress, Notifications, Profile, Settings, site shell, shaped skeletons, route contracts, and a large `learner-clarity.css` visual pass. Inspect all diffs; Antigravity was constrained to UI files but its session disappeared before a final report.

### Safe localhost-to-staging/VPS API adapter

Relevant files:

- `apps/learner-web/app/lib/dev-api-proxy.ts`
- `apps/learner-web/app/lib/dev-api-proxy.test.ts`
- `apps/learner-web/app/v1/[...path]/route.ts`
- `apps/learner-web/next.config.ts`
- `.env.example`
- `docs/contracts/ENVIRONMENT_CONTRACT.md`
- `docs/runbooks/LOCAL_VPS_DATA_PREVIEW.md`

Intended behavior:

- Development-only.
- Loopback API origin supports normal local reads/writes and preserves browser origin/cookies.
- The only allowed remote origin is exactly `https://api-staging.authorityclosers.com`.
- Remote mode permits anonymous `GET /v1/programs` and `GET /v1/programs/{slug}` only.
- Strip cookies, authorization, proxy authorization, and `Set-Cookie`; never forward user auth to staging through localhost.
- Reject private reads, mutations, arbitrary remote origins, and production origins before upstream access.
- Discover uses real published staging catalog data but disables enrollment and protected-data claims in public preview mode.
- The earlier focused proxy/shell run reported 37 passing tests, but rerun from the current worktree.

Do not connect localhost directly to the production database. Local testing must go through the API boundary. If authenticated staging testing is needed, use the real staging origin/session or an explicitly authorized credential flow, not copied secrets or forwarded browser cookies.

### Encrypted offline read cache

Relevant files:

- `apps/learner-web/app/lib/offline-read-cache.ts`
- `apps/learner-web/app/lib/offline-read-cache.test.ts`
- `apps/learner-web/app/lib/learner-api.ts`
- `apps/learner-web/app/lib/learner-api.test.ts`
- `apps/learner-web/app/components/sign-out-control.tsx`
- `apps/learner-web/app/lib/sign-out-control.test.ts`

Intended architecture:

- Versioned IndexedDB owned by the app; never use service-worker CacheStorage for `/v1`.
- AES-GCM 256 with a nonextractable browser key stored in IndexedDB.
- Honest limitation: encryption protects casual at-rest inspection, not XSS or hostile same-origin JavaScript.
- Owner-scoped entries, maximum seven-day age, bounded allowlist only.
- Cache eligible successful GET responses such as `/v1/me`, onboarding, bounded program listing, exact program detail, and exact learning-state reads.
- Exclude context/activity/drafts/evidence/certificates/auth, all mutations, and any canonical writes.
- Fall back only on genuine network failure; never on `AbortError`, API errors, 401, or 403.
- Purge owner data on 401/403 and purge all local/offline data on logout.
- Cached responses carry provenance metadata so UI can label stale/offline data and disable actions that require live authority.

The prior Luna worker disappeared before returning a final report. Review this implementation line by line, finish type safety/tests, and then integrate cached provenance into every relevant runtime.

### Request cancellation

Cancellation and stale-result protection were added to learner, progress, and settings runtimes. Verify signal propagation, unmount guards, and retry behavior.

### Media foundation

Provider-neutral media contracts exist under:

- `packages/python/ac_platform/media/`
- `tests/unit/media/`

Earlier evidence reported 19 media tests plus Ruff/mypy passing. Rerun. Do not claim a player or streaming deployment is complete without runtime evidence.

## Required immediate sequence

1. Inspect the full dirty diff and classify Antigravity/Luna edits; preserve valid work and fix incomplete code.
2. Run focused frontend tests and TypeScript checks; finish offline provenance UI and safe action disabling.
3. Rerun the complete frontend suite, lint, typecheck, build, media tests, Ruff, and mypy.
4. Start the local learner app and use Chrome for desktop/mobile visual and interaction QA.
5. Create same-viewport composites against all three reference images; fix every P0/P1/P2 mismatch. Create project-root `design-qa.md` ending exactly `final result: passed` only after it is true.
6. Use a fresh GPT-5.6 Luna `xhigh` review agent for the completed diff; fix blockers and rerun evidence.
7. Commit the exact bounded slice and push it. Run exact-SHA CI.
8. Deploy the exact artifact to staging through the repository pipeline and perform authenticated staging smoke/design checks.
9. Deploy the same artifact to production only if the documented production approvals, DB/recovery evidence, rollback proof, and action-time authorization are satisfied. Otherwise report the exact production blockers; never claim production is live prematurely.

## Deployment truth

Current controlled documentation says the production app/admin/API are `CONFIGURED_NOT_DEPLOYED`. Production requires reviewed exact staging release, G1/G2 approval, production DB/recovery proof, provider approvals, rollback proof, and separate production action-time approval. Staging may proceed after exact-SHA validation. The user wants the new UI live, but safety and controlled release gates remain authoritative.

## Current status snapshot

At handoff, the dirty worktree contains roughly 3,000 lines of tracked changes plus untracked route/runtime/design/offline/media files. The known earlier frontend baseline was 195 passing tests before the most recent Antigravity/offline changes. Node on the workstation was 22.17 while the package expects Node 24; exact environment proof must come from CI or a matching local runtime.

The next task must begin with repository evidence, not assumptions, and continue immediately toward a staging-visible UI plus safe localhost-to-staging data preview.
