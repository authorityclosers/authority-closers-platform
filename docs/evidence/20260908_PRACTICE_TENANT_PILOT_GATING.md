# Explicit tenant-scoped earned Practice pilot

## Implemented boundary

`AC_PRACTICE_PILOT_ENABLED` defaults false; the optional
`AC_PRACTICE_PILOT_TENANT_ID` defaults unconfigured. Enabling requires test,
staging or production and an exact match to the configured public learner
tenant, distinct from the operations tenant. Local/test preview remains a
separate mode. Mixed modes, deployed local-preview flags, missing scope or a
foreign pilot tenant fail closed. Disabled configuration mounts no Practice
routes. Runtime composition revalidates even a copied Settings object.

The existing application still freshly locks and validates Person, session,
selected tenant, active membership and active tenant before operations and
replays. HTTP retains exact safe Origin, strict request bodies, no account/tenant
query selectors, caller-owned idempotency, revision checks and function-scope
commit before success. Deployment exposes catalog and durable attempt APIs,
not the old local-only stateless `/sets/{set_id}/check` comparator.

No reward or Focus semantics changed: the first two distinct set families per
saved-timezone day earn 10 credits and 30 XP each; three actual practice days
earn 40 credits once per ISO week. Existing optional Focus behavior is retained.
No purchased currency, external AI evaluation, new penalties, consent updates,
official course progress or new schema migration was introduced. Content stays
explicitly editorial, not Dipak-reviewed assessment or competition material.

## Runtime frontend

The `/practice` route and `/practice/availability` presentation read are
`force-dynamic` and share the same runtime environment resolver; promotion
does not need a baked `NEXT_PUBLIC` pilot flag. The latter returns only
`{enabled:boolean}` with `private, no-store`, never identities or tenant IDs.
Shared navigation also requires successful current authenticated self-profile
admission from the existing Practice API. Disabled/malformed/missing runtime
availability, foreign/revoked admission and network failure hide the link.
Every actual Practice read and mutation remains backend-authorized.

The navigation probe is same-origin, cookie-preserving, redirect-refusing,
no-store and no-referrer, with a 1 KiB streamed response bound and six-second
total cancellation bound. It stores no grants or session data. Scope changes,
unmount and new refreshes cancel stale reads. Engine schemas load lazily only
after the runtime flag admits the feature. Existing unavailable Practice pages
retain explicit error/recovery states; no mock or local-preview fallback is used.

## Verification

- Five focused Python suites: **150 passed**, including 52 new deployment-pilot
  cases and unchanged earned reward/Focus/editorial regressions. The new cases
  use production-shaped Settings and real SQLite/FK/audit execution for both
  staging and production: exact scope, fresh lifecycle denial, persisted reward
  and balanced journal, idempotent replay, Origin/body/query refusal, disabled
  routes, stateless-check refusal, and HTTP commit-failure rollback.
- Eight frontend suites: **121 passed**, including runtime flag/route agreement,
  strict private bounded navigation requests, missing API recovery, cancellation,
  late-result rejection, shared sidebar visibility, and existing engine/Arcade
  behavior. Focused TypeScript and lint verification accompany this slice.
- Existing migrations 0020/0021 and their fixed reward/Focus rules are unchanged;
  recovery parity through 0022 remains the separate existing implementation.

This evidence records source and automated tests only. No environment activation,
runtime restart, browser interaction, production/staging account or database
write, provider call, deployment, content approval, retention policy or consent
change was performed. At that verification point, release profiles remained
disabled. A tenant-specific activation and production content/privacy approval
are separate decisions.

## Staging release-contract correction candidate — 2026-09-10

The reviewed earned-only pilot decision is now represented by the source-owned
staging profile: staging requires `AC_PRACTICE_PILOT_ENABLED=true`, while the
production profile and installer continue to require `false`. The installer
does not accept a separately selected pilot tenant. It clears any ambient value,
enters the managed environment, derives the pilot scope from the canonical
public learner tenant reference, and validates exact UUID shape and distinction
from the operations tenant before image loading or deployment mutation. Failure
messages contain no tenant references.

Compose resolves the target release's own profile for every call. A prior
immutable policy-off release therefore remounts neither Practice API nor
presentation routes. Deactivation does not downgrade schema, restore a live
database, delete balanced ledger rows, or rewrite immutable practice/audit
history.

Focused release, internal-transport, archive, settings, Practice pilot and
Practice HTTP regression: **358 passed, 6 skipped**. The skips require unavailable
local Caddy/Linux Docker integration surfaces; Bash syntax validation and Python
lint/format validation passed separately. This is source and test evidence only.
No managed setting, running flag, service, database, release artifact, deployment
or production state was changed by this correction.

Final independent review reported no Critical, Important or actionable Minor
findings. Its rollback regression composes separate current-on and previous-off
release directories and checks the canonical previous-release restart path.
Root's adjacent controller/internal-transport/film checks passed 109 with eight
explicit Windows POSIX/Docker skips after including the real scope helper in
the extracted-function test harnesses. The release archive suite passed 56.
Python lint/format and Git whitespace checks passed. Packaging and actual
staging activation are subsequent evidence, not implied by these local checks.
