# Academy username and opt-in leaderboard candidate

Date: 2026-09-10

Initial status: isolated `25ac` implementation and test evidence only. The root integration addendum below supersedes this initial status; the isolated-worktree verification is retained as provenance, not deployment evidence.

## Implemented contract

- One academy-scoped public profile per active learner membership. The database uniquely constrains the normalized username within that tenant; email is never selected into the public response.
- A username claim is self-only, safe-origin protected, private by default, retry-idempotent for the same normalized value, and immutable in this first release. ORM guards and a PostgreSQL trigger reject username/identity mutation or deletion, so membership removal cannot silently release a name for reuse. A competing database uniqueness result returns a generic unavailable response. Claim and privacy changes append tenant audit events in the caller-owned transaction.
- The candidate grammar is ASCII lowercase after trim/case normalization: 3–30 characters, starts with a letter, letters/numbers with single interior underscores. Reserved brand, staff, system, official, support, and Dipak-impersonation keys are rejected. This exact grammar/reserved set must be deliberately reviewed during root integration; it is not a production policy claim.
- Leaderboard participation is a separate revision-guarded opt-in. Withdrawal immediately removes the profile from the projection without changing earned XP, course progress, access, or scoring. Pagination cursors contain only XP and the tenant-unique username; they contain no person UUID or email and reject malformed field types with 422.
- The leaderboard is tenant-scoped and reads only positive, confirmed `PracticeRewardClaim.xp` facts for active, verified learner memberships with opted-in public profiles. It uses all-time totals and SQL competition `RANK`: equal XP receives equal rank. Username and person ID provide stable page order only. No email, prizes, analytics events, new XP rules, private-course activity, or AI evaluation enter the projection.
- The learner profile card uses existing Clarity Grid theme/status/focus tokens, 44px controls, a one-column compact layout, explicit loading/empty/error/offline/retry states, a non-login username explanation, and separate participation save. The frontend-design review was applied within the controlled product system rather than adding a competing shell or visual language.
- Profile and leaderboard reads settle independently, so an optional leaderboard failure does not block username claiming. Mutations use abort signals, synchronous in-flight guards, and generation checks so double submits and results from an unmounted or replaced academy identity context cannot overwrite current state. A saved opt-in remains saved if the follow-up leaderboard read fails; a 401 at that point exposes the normal sign-in recovery link.

## Verification in the isolated worktree

- `uv run pytest tests/unit/community tests/unit/http/test_community_routes.py tests/database/test_model_registry.py -q` — 45 passed; one existing Starlette TestClient deprecation warning.
- `uv run ruff check ...` over all new/modified Python and migration files — passed.
- `uv run mypy packages/python/ac_platform/community packages/python/ac_platform/http/community.py` — passed with no issues in four source files under the repository's strict mypy configuration.
- Python compile check for the new domain, HTTP boundary, and migration — passed.
- With repository Node `v24.19.0` and `NODE_OPTIONS=--max-old-space-size=768`, `pnpm --filter @ac/learner-web test -- app/components/community-identity-card.test.tsx app/lib/community-api.test.ts app/lib/revenue-journey-resume.acceptance.test.ts app/components/profile-runtime.test.tsx` — 4 files, 25 tests passed.
- With the same supported Node runtime, learner TypeScript and full learner-web ESLint — passed.
- `git diff --check` — passed.

New async/recovery regression names requested for integration review:

- `keeps username claiming available when the optional leaderboard read fails`
- `allows only one username claim while a mutation is in flight`
- `aborts and ignores an old mutation after its identity context is replaced`
- `offers sign-in recovery when the saved-participation refresh expires`

An earlier exploratory whole learner-web run under unsupported Node `22.17.0` was not used as acceptance evidence: 703 of 713 tests passed, while nine native privacy subprocess probes and one unrelated local-draft timing case failed. Per root direction it was not repeated; the owned test set, typecheck, and lint were instead rerun successfully under the required Node 24 runtime.

## Required root integration gates

1. Apply only the listed community/profile/API/model-registry/app-composition changes to current `d2de`; do not copy the old worktree wholesale.
2. Confirm migration `20260910_0027` follows current head `20260910_0026`, run upgrade/model-drift checks in a fresh disposable schema, and verify its deliberate forward-only downgrade failure plus the controlled restore/runbook path. No remote database mutation is authorized by this evidence.
3. Add/run real PostgreSQL concurrency cases proving exactly one winner for two people claiming the same tenant username, safe same-person retries, different-tenant reuse, revision-safe opt-in/withdrawal, audit-chain validity, and inactive/suspended participant exclusion.
4. Rerun current practice-engine/database regression to prove the projection did not alter reward issuance, ledger balance, XP totals, course progress, access, or scoring.
5. Browser-accept the mounted profile card at 320/390/768/1440 px in light/dark modes with keyboard, visible focus, loading, empty leaderboard, claim conflict, expired session, offline mutation, opt-in, withdrawal, and long-username wrapping.
6. Treat the ignored static return-intent prototype as design discussion only; it is not part of this implementation or its evidence.
7. Approve and persist the candidate reserved namespace before production activation. The database enforces normalized uniqueness and immutability but intentionally does not invent the authoritative brand/role reservation policy.
8. Decide and document the controlled username-correction/support path before representing recovery as operational. Current copy directs the learner to support; this candidate does not invent or implement a correction workflow.
9. Keep the current HTTP membership/learner-role admission fence for all callers. Any future direct application-service caller must establish an equivalent authenticated active-learner boundary before use.

## Root integration addendum

The allowlisted candidate was integrated into `d2de` on base `7bdd069d4bf00561edcab90b1679666205708185`, preserving existing Studio/media and unrelated user edits. The actual canonical `PracticeRewardClaim` model is directly imported and used in the query test. Cursor XP is bounded to a signed 64-bit nonnegative value, and duplicate or extra HTTP pagination keys are rejected.

The initial independent-settlement claim above was stronger than the original `Promise.allSettled` implementation. Root replaced it with genuinely independent reads and added a pending-leaderboard regression. Root also added identity-context clearing, stale leaderboard generation fences, small-screen table columns and unbroken username wrapping. The durable Arcade header links to the identity section.

Every community request now has a ten-second abortable deadline. Late completions are ignored. An uncertain timed-out mutation requires a canonical refresh before another mutation, preserving the typed name without falsely claiming the save failed. A successful participation save unlocks the controls without waiting for the optional leaderboard refresh. Those three regression cases failed before the change and passed afterward. User-facing text now states that usernames are fixed in this release; it no longer promises a support correction mechanism.

Independent review found two additional Important issues: nested FastAPI error codes did not reach the UI's specific messages, and failed-ranking copy falsely described an already-claimed name as available. Community errors now inherit the existing canonical `DomainError` and use the registered problem-details handler, tested with actual HTTP 409/422 envelopes and matching frontend adapter fixtures. Ranking failure copy is neutral. The requested follow-up review is separate from these test results.

Current root checks:

- Community/domain/HTTP/model-registry: 50 passed, with one existing Starlette TestClient dependency warning; Ruff and strict mypy passed (four source files).
- Real disposable PostgreSQL: seven passed, including simultaneous claims, same-person retry/audit behavior, cross-academy names, opt-in/withdrawal, real-journal XP/tied ranks/filtering, immutable identity, and migrated-table/ORM drift. Each uses an isolated temporary schema, not an operational SQL repair.
- Mounted community/API/Arcade: 38 passed after the recovery/error-envelope fixes. Earlier full learner run: 1,438 passed across 75 files; a later full run is required if claiming whole-suite acceptance of the final delta.

Before the normal local API migration, the marked disposable database was backed up with `Backup-LocalSandbox.ps1`: `.tmp/local-platform/backups/before-community-identity-20260909T211717373Z.dump`, 617,487 bytes, 805 archive entries, SHA256 `43D1FCA7091C1727D5EA7409CB35DB71361DF8A161994F0B301607C896B00E85`. The managed API restart applied `0025 -> 0026 -> 0027` through Alembic, preserving existing local accounts and content. No remote database, provider, permissions, reward policy or live offer changed. Normal-browser acceptance and remote backup-contract/release gates remain outstanding at this addendum.

Subsequent whole learner regression: **1,445 passed in 75 files** on Node24. The managed local API was restarted again after the canonical problem-envelope correction; Alembic had no additional migration to apply.

Root added versioned backup/restore inventories to all three separately packaged helpers: exact head `20260910_0026` uses `ac-postgres-parity-v6` (54 tables, adding `studio_video_uploads`), and `20260910_0027` uses `ac-postgres-parity-v7` (55 tables, adding `academy_public_profiles`). Older heads/contracts remain unchanged and unknown `0028` still fails closed. The exact migration-table/contract assertion failed before implementation and passed afterward. The expanded parity suite passed 286 tests; backup/restore regression passed 59 with seven documented POSIX-only skips on Windows. Ruff passed. These are local contract tests, not proof that VPS foundation helpers have been upgraded or a live restore drill has run.

## Normal-browser acceptance

Independent community re-review found no remaining Critical/Important findings. A fresh isolated Chrome session used normal localhost login as the existing synthetic learner, without injected authentication/storage state or SQL/seed operations. Initial run `.tmp/proof/community-identity-qa/run-20260909T213630Z/proof.json` records reserved-name HTTP422 and successful username-claim HTTP200, but its later harness assertion failed; it is claim-response evidence only, not a whole-flow pass. CSS-module/status selectors were corrected in the test harness. Complete run `run-20260909T214505Z/proof.json` then passed existing `@local_learner` reload persistence, opt-in/withdrawal, canonical rank1/90XP, 320/390/768/1440 light/dark, keyboard focus and labelled GET-only 401/slow/offline recovery. Fourteen screenshots, zero page errors and no horizontal overflow; final participation opted out. No XP was fabricated, and unavailable taken-name browser coverage is not claimed for the initially empty board (HTTP/DB collision tests cover it).

Root visually inspected desktop opted-in and mobile dark captures and caught contradictory static helper copy saying participation was off after a successful join. The helper now reports the canonical saved opt-in, not the pending checkbox value. The component regression asserts off before save, still off after merely toggling, and on only after confirmed save. Focused community/API tests passed21 after this copy correction. A separate final-copy browser rerun is recorded after acceptance, not substituted for the earlier fresh-claim response.

Final-copy rerun `.tmp/proof/community-identity-qa/run-20260909T215215Z/proof.json` passed with fourteen captures, normal UI login, all four widths/light-dark variants, keyboard and recovery fixtures, saved-participation assertions on both sides of Save, zero page errors/overflow and final opted-out state. Its writes were login and participation only. Its immediate optional-ranking snapshot was empty; canonical rank/90XP rendering evidence remains the separate `214505` run above, not an assertion about this immediate snapshot.

## Clean candidate assembly

The next candidate is assembled in a separate clean worktree on branch
`codex/community-identity-arcade-candidate`, based exactly on deployed Coach
commit `783da9838179ee32f0481d9bae9a8b1b30a95ec4`. Its source was the allowlisted
working-tree content in `d2de`, whose observed checked-out commit remained
`7bdd069d4bf00561edcab90b1679666205708185`; no whole-tree copy or source-tree
mutation was used. The candidate commit is recorded in the release handoff
after this evidence file is frozen.

Candidate manifest (33 files):

```text
apps/learner-web/app/components/community-identity-card.module.css
apps/learner-web/app/components/community-identity-card.test.tsx
apps/learner-web/app/components/community-identity-card.tsx
apps/learner-web/app/components/practice-arcade.module.css
apps/learner-web/app/components/practice-arcade.test.tsx
apps/learner-web/app/components/practice-arcade.tsx
apps/learner-web/app/components/profile-runtime.tsx
apps/learner-web/app/lib/community-api.test.ts
apps/learner-web/app/lib/learner-api.ts
apps/learner-web/app/lib/revenue-journey-resume.acceptance.test.ts
apps/learner-web/app/theme.css
db/migrations/versions/20260909_0024_studio_media_library_index.py
db/migrations/versions/20260909_0025_studio_course_creation.py
db/migrations/versions/20260910_0026_studio_video_uploads.py
db/migrations/versions/20260910_0027_academy_public_profiles.py
docs/evidence/20260910_ACADEMY_COMMUNITY_IDENTITY_CANDIDATE.md
infra/application/scripts/restore-drill.py
infra/vps-foundation/scripts/ac-postgres-backup.py
infra/vps-foundation/scripts/ac-restic-postgres-restore-proof.py
packages/python/ac_platform/catalog/models.py
packages/python/ac_platform/community/__init__.py
packages/python/ac_platform/community/application.py
packages/python/ac_platform/community/models.py
packages/python/ac_platform/db/models.py
packages/python/ac_platform/http/app.py
packages/python/ac_platform/http/community.py
packages/python/ac_platform/media/models.py
tests/database/test_model_registry.py
tests/infra/test_capability_backup_parity.py
tests/integration/test_community_identity_postgresql.py
tests/unit/community/test_application.py
tests/unit/community/test_username_policy.py
tests/unit/http/test_community_routes.py
```

The shared HTTP installer includes only the community import and install call.
Migration `0026` remains dormant: no Studio media/video endpoint, provider,
storage, processor, transport, worker or outbox activation is present. Course
creation services and Operations UI are also excluded. The explicitly approved
post-assembly corrections affect only the `0024` and `0027` downgrade error
messages so both state the existing forward-only recovery policy; their
revision metadata and upgrade bodies are unchanged.

Candidate-owned verification used Node `v24.19.0`, pnpm `11.19.0` and
`NODE_OPTIONS=--max-old-space-size=768` where applicable:

- post-review focused community/domain/HTTP: 50 passed; one existing Starlette/httpx deprecation warning;
- Ruff: passed; strict mypy: four source files passed;
- disposable loopback PostgreSQL: seven passed, with an isolated migrated schema;
- exact backup parity: 286 passed, including v6/54 and v7/55 while preserving legacy contracts;
- backup/restore regression: 98 passed and nine documented Windows/opt-in skips;
- existing catalog regression: 11 passed without adding the non-allowlisted source test delta;
- final full learner-web after the Important fixes: 1,446 passed across 75 files;
- learner, Admin and Coach typechecks: passed sequentially;
- learner ESLint: passed with zero warnings;
- learner production build: passed, 25 routes, before the review-only race/a11y hardening; the final hardening was re-typechecked and linted;
- Prettier and `git diff --check`: passed.

The `214505` and `215215` browser records above are source-integration evidence,
not exact-commit acceptance for this clean candidate. Independent review and
exact-candidate browser acceptance remain root-controlled release gates.

Initial clean-candidate commit `99fdc62bf43ce1206871502cb58176cf1eb2214e`
was superseded before acceptance after independent review found two Important
issues: leaderboard retry could race an in-flight mutation, and community
mutations did not enforce an explicit caller-owned transaction. The amended
candidate gates refresh during mutations and enforces that transaction origin,
with focused regressions. The final handoff SHA is authoritative.

Before a staged database can advance to `0026`/`0027`, the foundation runtime
must receive these reviewed backup helpers through the repository's canonical
checksum-bound archive path. From the same verified archive, the controlled
gate is `bootstrap-host.sh runtime` with `AC_RELEASE_ID`, `AC_RELEASE_ARCHIVE`
and `AC_RELEASE_ARCHIVE_SHA256` supplied by the existing Ansible bootstrap
playbook. Only after a healthy current staging application, Infisical bootstrap,
R2 usage guard and capture/restore prerequisites exist may the separate
`bootstrap-host.sh activate postgres-backup` gate run. That gate performs the
existing dry-run and capture-only proof before enabling its timer. No manual
file copy, operational SQL, remote foundation change or activation was performed
for this candidate.
