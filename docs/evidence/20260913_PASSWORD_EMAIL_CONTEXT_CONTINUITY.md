# Password email context continuity

Date: 2026-09-13 (Asia/Kolkata). Source base: `ea5998c`; implementation checkpoint:
`6e4f59f`. Bounded implementation and validation are recorded. This document
records the email slice only; it is not a provider or deployment claim.

## Exact implementation and test allowlist

The email delta contains these **19 implementation/test paths**.
Other paths in the shared worktree are unrelated and are excluded from this
cut.

### Implementation paths

- `apps/learner-web/app/components/login-form.tsx`
- `apps/learner-web/app/components/password-auth-forms.tsx`
- `apps/learner-web/app/components/staging-auth-handoff.tsx`
- `apps/learner-web/app/forgot-password/page.tsx`
- `apps/learner-web/app/lib/activity-intent.ts`
- `apps/learner-web/app/lib/course-intent.ts`
- `apps/learner-web/app/lib/learner-api.ts`
- `apps/learner-web/app/reset-password/page.tsx`
- `apps/learner-web/app/verify-email/page.tsx`
- `packages/python/ac_platform/http/auth.py`
- `packages/python/ac_platform/identity/password_auth.py`
- `packages/python/ac_platform/outbox/repository.py`
- `packages/python/ac_platform/worker/__init__.py`

### Test paths

- `apps/learner-web/app/components/password-email-continuity.test.tsx`
- `apps/learner-web/app/lib/learner-ui.test.ts`
- `tests/unit/http/test_password_email_continuity.py`
- `tests/unit/outbox/test_jobs.py`
- `tests/unit/outbox/test_password_email_context_jobs.py`
- `tests/unit/worker/test_worker.py`

The evidence artifact is this additional path:
`docs/evidence/20260913_PASSWORD_EMAIL_CONTEXT_CONTINUITY.md`.

The narrow Google `registration_required` password-recovery companion was
committed separately in `ea5998c` and is intentionally outside the
email commit allowlist: `apps/learner-web/app/auth/callback/page.tsx`,
`apps/learner-web/app/components/google-activity-continuity.test.tsx` and
`docs/evidence/20260913_GOOGLE_EXISTING_PASSWORD_RECOVERY.md`. It preserves the
same validated context and is covered by that companion evidence.

The existing registration page and Google/auth-link helpers are consumed as
already-validated dependencies from the prior course/Google continuity cuts;
they are not changed by this email delta. No database migration, identity
authority, enrollment, access, consent policy, provider configuration or
Sales-auth return path is in this allowlist.

## Contract and boundaries

- A request without navigation context emits the exact existing v1 event and
  job shape. Existing queued v1 jobs remain readable.
- A request with the fixed course slug
  `authority-closers-free-course` emits the versioned v2 verification or reset
  event. Its required payload keys are `challenge_id`, `kind` and `course`.
  `activity` is optional and is normalized to a canonical hyphenated UUID.
- Course-only links use the fixed internal verification/reset route with the
  course query and keep the one-time token in the URL fragment. Course-plus-
  activity links add the validated activity query before that fragment.
- The HTTP models reject an activity without the allowlisted course, an
  unknown course, malformed UUID, extra JSON key or non-object payload.
  Frontend parsers discard invalid navigation hints, including duplicate
  query arrays; valid course-only context can remain after an invalid activity.
  The worker applies the versioned route schema before constructing a link.
- Fixed learner destinations and the configured learner origin are used. The
  context is navigation-only and cannot grant identity, tenant, enrollment,
  access or privilege. No arbitrary return URL, client tenant or provider call
  is accepted.
- Registration, recovery and verification resend carry the context into the
  appropriate v2 event. Verification success continues to onboarding with the
  context; reset success returns to password login with the context; error and
  retry links preserve it. A Google `registration_required` result offers the
  existing password sign-in path with the same validated context and explains
  that Google can be connected later from account settings. Consent and the
  existing no-auto-link behavior remain required.
- `OutboxJobRoute.optional_payload_keys` is at the end of the dataclass fields,
  preserving the existing positional constructor contract. The compatibility
  tests in `tests/unit/outbox/test_jobs.py` cover the legacy positional route,
  exact v1 schema rejection and bounded optional-key validation.

## Validation receipts

The release packet retains the latest bounded Python receipt at:

`D:/Projects/authority-closers-release-transfer/2026-09-11-recovery/email-continuity-expanded-python-final.log`

It records the expanded current run: **77 passed in 6.79s**. This includes the
HTTP, worker, outbox and compatibility coverage after moving the optional
route field to the end.

The retained focused learner receipt used Node `24.19.0`, one Vitest worker and
`--max-old-space-size=384`:

`D:/Projects/authority-closers-release-transfer/2026-09-11-recovery/email-continuity-frontend-final.log`

It contains the following command:

```text
pnpm --filter @ac/learner-web exec vitest run \
  app/components/password-email-continuity.test.tsx \
  app/components/google-activity-continuity.test.tsx \
  app/lib/learner-api.test.ts \
  app/lib/course-intent.test.tsx \
  app/lib/learner-ui.test.ts
```

The run passed **179 tests across five files**. The email-specific input is
`app/components/password-email-continuity.test.tsx`; the adjacent committed
Google recovery test and the three existing consumer/contract tests were also
exercised to check compatibility. The newly added wrapper regressions account
for five of the file's **11 passing tests**.

Earlier focused Python coverage before the final outbox compatibility move is
also retained as **40 passed** for:

```text
tests/unit/http/test_password_email_continuity.py
tests/unit/worker/test_worker.py
```

The final full learner suite passed **1,711 tests across 95 files** on Node
24.19.0 with one worker and a 384 MiB parent heap. Receipt:
`email-continuity-learner-all-final.log`. Learner TypeScript also passes with a
640 MiB heap (`email-continuity-learner-types-final.log`). These receipts are in
the same release packet. No full production build or external email/provider
delivery is claimed here.

## Acceptance boundary

### Final backend review coverage

`email-continuity-python-final.log` in the release packet records **186 passed**
across the password-email routes, auth routes/transactions, password identity,
outbox and worker tests. Nine TestClient cases exercise actual route forwarding
for registration/recovery/resend across v1, course-only and course/activity.
Two materialization cases invoke the real repository method using the existing
mocked session harness; they verify normalized jobs and event publication.
These two cases do not claim a live database queue or external provider run.
Scoped Ruff and format checks pass for eight Python paths; mypy passes for the
four changed Python source modules.

### Deployment sequence

No worker lacking the v2 event/job allowlists may consume events after the API
starts emitting v2 requests. A rolling rollout can install compatible workers
first. The current release installer instead stops the old worker before
starting the new API and then starts the new worker; the durable events can
safely queue during that interval. Keep worker compatibility with v1 while
existing jobs drain. This cut contains no migration or provider activation.

The local API was restarted at `6e4f59f` for acceptance. Final independent review
identified a pre-existing non-string allowlist bypass in the outbox payload
normalizer. The follow-up requires strings before checking allowed values and
adds seven regressions, preserving unrelated primitive fields and UUID
coercion. Main independently reviewed the three-path fix; the bounded run
passed 63 tests plus Ruff/format/mypy. The final expanded auth/outbox/worker
suite passed **193 tests** (`email-continuity-schema-python-final.log`).
The schema follow-up is `02bdb91fdf2bf47d107656cc2664daaee6c669d4`.
External email delivery and production deployment remain outside this local
acceptance. The separate Sales Xray login return destination is a dependent
follow-up outside this email cut.

### Canonical fresh-browser acceptance — passed

The local API and auth source were frozen at `02bdb91`. The accepted receipt is
`canonical-email-continuity-20260912T235916Z/proof.json` in the release packet.
It records the exact source hashes and reusable helper hash.

- Normal registration persisted the canonical person, verification challenge
  and course-only v2 outbox event. The actual worker message resolver built the
  verification link from those records. A fresh browser verified the same
  person, removed the token fragment and retained the course at onboarding.
- Normal password recovery persisted a course/activity v2 outbox event for the
  prior synthetic draft subject. The actual resolver built the reset link. A
  fresh browser consumed it, reset the password, signed in and automatically
  returned to the same activity with the server draft still visible.
- Snapshots of enrollment, entitlement, draft, progress, learning evidence and
  evidence submission tables for that subject were unchanged. Canonical
  completion remained zero of five. No learning mutation was issued.
- Verification/reset screenshots passed 320/1440 reflow; the returned activity
  passed at 390. Main inspected the mobile images. No page errors, blocked
  requests or unexpected API status codes occurred.

The helper uses the installed psycopg async dialect with a Windows selector
event loop, reads persisted outbox records and rolls back after resolving the
message. It does not materialize jobs, dispatch a worker or contact a provider.
Queue materialization is covered separately by the repository tests above.
The browser proof is synthetic local acceptance, not real recipient delivery.

Earlier helper failures are retained in `canonical-email-continuity-` folders
ending `235600Z`, `235727Z` and `235829Z`: an ambiguous consent selector, an
uninstalled asyncpg driver and the Windows psycopg event loop. The corrected
helper selects the actual checkbox, uses the installed driver and a selector
loop, and uses the model's generic JSON accessor. Product source did not change
between those attempts and the accepted run.
