# Learner course-first UI increment

Status: implementation candidate on `codex/course-first-ui-v01`; no commit,
deployment, or production approval is claimed.

## Scope

This increment refines the existing authenticated `/learning` My Learning
collection. It keeps the current API-backed collection read, cursor pagination,
all/in-progress/completed/saved filters, membership boundary, route-shaped
loading/error/empty handling, and responsive learner shell unchanged. The
existing encrypted offline-read-cache architecture now allowlists only the
authenticated self read (`/v1/me`) and the exact bounded learning collection
pages (`/v1/learning?limit=50` with an optional opaque cursor) for this route.
Cached responses are owner/tenant-scoped, labeled stale/read-only, and never
used to authorize access; the owner binding is written and read back through
durable sessionStorage before the in-memory mirror advances. A failed binding
purges/invalidates the private scope and fails closed, while a 401/403 still
purges private cache and a missing cache preserves the live failure.

Each course card now has one state-based dominant action:

| Canonical collection state | Action label    | Destination                          |
| -------------------------- | --------------- | ------------------------------------ |
| `in_progress`              | Continue course | Existing `/learn/{programSlug}` path |
| `completed`                | Review course   | Existing `/learn/{programSlug}` path |
| `unavailable`              | Open course     | Existing `/learn/{programSlug}` path |

The adapter derives only from `state`, `projection`, `saved_state`, and the
existing `program_slug` navigation field. It does not fetch a second
per-course resource, infer an activity ID, grant access, or turn a URL into
authorization. `unavailable` is presented as unavailable progress, not as a
canonical locked state; the destination route server-rechecks access and any
course/module state before rendering.

## Implementation evidence

- `apps/learner-web/app/components/learning-course-card.tsx` contains the
  reusable card, status badge, bounded progress projection, and state-to-action
  mapping.
- `apps/learner-web/app/components/learning-runtime.tsx` remains responsible
  for collection loading, cursor traversal, filtering, membership cleanup,
  retryable-vs-terminal error states, keyboard-accessible filter tabs, and
  route-level states; 408/425/429, network, and 5xx failures are retryable,
  401 is sign-in/session recovery, 403 is safe permission denial/support with
  no generic Retry CTA, and other bounded 4xx failures are terminal. It labels
  cached content as a read-only snapshot and card rendering is delegated to
  the adapter.
- `apps/learner-web/app/course-surfaces.css` adds token-backed next-action and
  saved-state treatments, 44px filter targets, and token-backed unavailable
  progress styling while retaining the selected Clarity Grid shell and existing
  desktop/mobile breakpoints.
- `apps/learner-web/app/lib/offline-read-cache.ts` retains encrypted IndexedDB,
  versioned owner/tenant scoping, retention/size bounds, and purge behavior;
  only the self and paginated learning collection reads were added to its
  allowlist. Activating, rebinding, and purging advance a cache-owned owner
  generation; private writes receive an immutable owner lease only after the
  durable sessionStorage binding is written and read back. The generation is
  part of each private cache key, and private puts revalidate the lease
  immediately before and after the asynchronous IndexedDB write, removing a
  stale record if an owner switch or purge wins during the write. Private reads
  capture the same lease and revalidate after the asynchronous record read and
  after decrypt, so an owner switch or purge returns no stale payload.
- `apps/learner-web/app/lib/learner-api.ts` binds each API instance's private
  writes to the lease returned by the shared cache; there is no per-instance
  readiness boolean or memory-owner authorization fallback.
- `apps/learner-web/app/lib/learner-course-surfaces.test.ts` verifies action
  mapping, canonical progress handling, saved-state visibility, safe route
  destinations, the absence of fabricated activity links or lock claims,
  cursor traversal, filter transitions, keyboard tab behavior, and
  retryable-vs-terminal classification and controlled 401/403 actions.
- `apps/learner-web/app/lib/learner-api.test.ts` and
  `apps/learner-web/app/lib/offline-read-cache.test.ts` cover online cache
  writes, offline self/collection fallback, missing-cache failure, 5xx no-stale
  fallback, allowlist boundaries, owner-scoped encrypted page recovery,
  activation-result-gated private writes, separate API/cache-instance lease
  binding, deterministic deferred reads/decrypts and writes during owner
  switch and logout/purge, and throwing-sessionStorage cross-person/tenant
  invalidation.

## Source boundary

The implementation follows `LEARN-01` in the learner screen-family state
matrix, the `ProgramCard`/`NextActionCard` component contract, the selected
Direction A shell plus Direction B learning treatment, and the repository
authorization/data contracts. Visual references remain reference evidence;
this file does not claim exact-current browser/device or staging proof.

## Validation

- `pnpm --filter @ac/learner-web test` — 26 files, 361 tests passed.
- `pnpm --filter @ac/learner-web typecheck` — passed on Node 22.17.0; the
  repository requests Node 24, so this is local typecheck evidence only.
- `pnpm --filter @ac/learner-web lint` — passed.
- `pnpm --filter @ac/learner-web build` — passed; Next generated the existing
  25-route production route table.
- `pnpm exec prettier --check` on changed implementation/tests/evidence — all
  changed files matched.
- `git diff --check` — passed.
- `apps/learner-web/next-env.d.ts` is unchanged from `origin/main` after the
  build check.
- Branch rebased onto `origin/main` at `eb183791cf7213eb33c585846c136cd38c673c95`;
  the reviewed implementation is committed on the feature branch.
- Controlled learner package validator — passed: 187 matrix rows, 11 flows,
  38 screens; visuals pending (0 assets).

Remaining limitations are the existing controlled gates: exact current-SHA
browser/device evidence, real staging protected-data proof, and independent
accessibility/release approval remain open. No Playwright or alternate browser
was used for this increment.
