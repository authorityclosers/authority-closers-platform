# Integrated release validation — 2026-09-10

Status: in progress against the authoritative working tree at
`C:\Users\Suyash\.codex\worktrees\d2de\authority-closers-platform`, branch
`codex/release-setgid-fix`, base HEAD
`7bdd069d4bf00561edcab90b1679666205708185`. The candidate remained dirty and
continued to receive reviewed work during this checkpoint. No file was staged
or committed, no database migration was applied, no service was restarted, and
no staging or production deployment was performed.

## Node 24 integrated checkpoint

Commands used the repository-declared Node line through the bundled
`v24.19.0` runtime and pnpm `11.19.0`.

| Gate | Result |
| --- | --- |
| `pnpm exec prettier --check apps packages/typescript package.json pnpm-workspace.yaml .github/workflows/application.yml` | Passed after two narrowly owned files were formatted. |
| `pnpm -r --if-present lint` | Passed after the sound-control issue below was fixed and independently reviewed. |
| `pnpm -r --if-present typecheck` | Passed for UI, learner, admin and coach packages. |
| `pnpm -r --if-present test` | Passed: learner 77 files / 1,477 tests; admin 25 / 579; coach 1 / 14. Total 103 files / 2,070 tests. |
| `git diff --check` | Passed. |

The first formatting check found exactly
`practice-sound-controls.tsx` and `practice-music.ts`. Prettier was applied only
to those assigned files. The first Node 24 lint found
`react-hooks/set-state-in-effect` at `practice-sound-controls.tsx:76`. The
correction moved preference-off cancellation into the external-store event:
it advances the pending request generation, clears the real loading state and
stops the player. A regression test proves a late successful start cannot
restore read preference or UI. Focused Prettier/ESLint passed and the two audio
suites passed 12 tests. An independent Luna review found no Critical or
Important issue.

The first parallel unit attempt was not accepted as evidence: it ended after
1,447 passing assertions because installed `zod`/`happy-dom` files were briefly
unavailable to Vitest workers. The files were present immediately afterward;
the serial full rerun above completed cleanly without a dependency repair.

## Python non-media checkpoint

Media publication source and related tests were changing in a parallel owned
slice, so this checkpoint intentionally excluded
`packages/python/ac_platform/media/**` and Python files matched as directly
media/video/Studio/public-film related.

| Gate | Result |
| --- | --- |
| Ruff format check | 231 stable Python files passed; 162 related files excluded. |
| Ruff lint | The same 231 files passed. |
| Pytest stable unit slice | 67 files / 1,145 tests passed; one existing FastAPI/httpx deprecation warning. |

This is useful isolation evidence, not a substitute for the final full Python
Ruff, mypy and pytest gates after the media slice stops changing.

## App Updates backend addition

The approved learner-only release-update contract now has:

- authenticated `GET /v1/me/app-updates`;
- idempotent `POST /v1/me/app-updates/app-updates-v0-2-alpha/read`;
- exact learner-host, selected learner-membership and safe-origin admission;
- no person, tenant, filter or body selectors;
- private `no-store` headers on success, authentication, validation and denial;
- one current-artifact catalogue entry, “A home for app updates” / `v0.2 Alpha`;
- append-only person-and-tenant-scoped read receipts in forward-only migration
  `20260910_0029`; and
- no email, push, marketing, scoring, progress or payment semantics.

Focused Ruff and mypy passed. App-update application, HTTP and model/migration
tests passed 36 tests; the broader route/serve/health/model-registry selection
passed 119 tests before the final bounds additions. A fresh schema inside the
managed loopback-only PostgreSQL sandbox was migrated to 0029 and both
app-update integration tests passed. They prove cross-session persistence,
cross-person and cross-tenant isolation, plus a real two-transaction barrier
race in which both callers observe `read=true` and exactly one scoped receipt
is retained. The harness dropped its disposable schema; migration 0029 was not
applied to any runtime schema.

Independent review found that adding migration 0029 without a new backup parity
row would make all canonical backup/restore helpers fail closed. The three
separately packaged parity catalogues now include explicit
`ac-postgres-parity-v9` with `app_update_read_receipts`, and all 372 cross-module
parity tests pass.

## Build isolation finding

There is no existing safe local build-output switch. Each app runs plain
`next build`; all three configs use `output: "standalone"` without a separate
`distDir`; installed Next defaults to cleaning `.next`; and the active local
launchers use the same app directories for `next dev` / `.next/dev`. Therefore
no local build was run. The existing isolated build path is the canonical
BuildKit/CI application image build in `infra/application/Dockerfile.web`.

## Remaining release gates

1. Finish and review the parallel media-publication and learner Notifications
   UI slices, then regenerate the explicit candidate allowlist. The earlier
   251-path inventory is scope guidance, not proof for the expanded tree.
2. Run full repository Prettier/Ruff, ESLint, mypy and all Node/Python tests on
   one stable exact tree. Explicitly include the standalone
   `packages/typescript/operations-web` Studio-video tests because that package
   has no recursive `test` script.
3. Run the complete disposable migration/schema-drift suite through the
   canonical test harness on the final tree; the app-update-specific
   PostgreSQL isolation and parity suites already pass.
4. Build the exact candidate only through the isolated container/CI path; do
   not run an app-local Next build while the live development `.next` trees are
   active.
5. Reconcile the staged manifest to the final allowlist, review the exact diff,
   run both Application and Control-plane CI, and package/deploy only the
   digest-bound exact commit through the canonical staging controller.
6. Treat production as a separate release decision and retain its previously
   identified configuration/secret-presence gate.
