# Password email context continuity

Date: 2026-09-13 (Asia/Kolkata). Candidate source base: `ea5998c`. Status:
bounded implementation and validation recorded; the email delta remains
uncommitted in the d2de worktree. This document records the email slice only;
it is not a provider, deployment or complete new-device acceptance claim.

## Exact implementation and test allowlist

The current pending email delta contains these **19 implementation/test paths**.
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
committed separately in `ea5998c` and is intentionally outside the pending
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

Deploy the worker with the v2 event/job allowlists before the API and learner
start emitting v2 requests. An old worker cannot process these new versions.
Keep worker compatibility with v1 while existing jobs drain. This cut contains
no migration or provider activation.

The current API process remains frozen to the release owner's prior backend
checkpoint while the email delta is reviewed. A new-device browser receipt,
worker execution against a running release, external email delivery and
production deployment remain pending. The separate Sales Xray login return
destination is a dependent follow-up and is outside this email cut.
