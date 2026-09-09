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
change was performed. Release profiles remain disabled. A tenant-specific
activation and production content/privacy approval are separate decisions.
