# Learner local draft recovery contract

Status: v0.1 Alpha implementation contract

Browser storage is a bounded recovery cache only. It is never canonical
onboarding, progress, draft, evidence, completion, entitlement, or audit state.
The server remains authoritative.

## Scope and concurrency

- Onboarding recovery is scoped to the authenticated person.
- Activity recovery is scoped to tenant, person, enrollment, and activity.
- Every envelope records the server base revision and a deterministic
  fingerprint of the server content visible when editing began.
- A recovery copy may enter the editor automatically only when both values
  still match. Any mismatch presents server and local values separately and
  requires an explicit keep-server/discard-local or use-local-in-editor choice.
- Choosing the local copy moves it into the editor against the latest loaded
  server base. It does not write to the server until the learner uses the
  explicit save or submit action.

## Retention and cleanup

- Recovery envelopes expire seven days after their most recent local write.
- A successful server save removes the corresponding recovery copy.
- Successful sign-out purges all learner recovery copies on the origin while
  preserving unrelated preferences such as appearance.
- A known unavailable membership purges learner recovery copies.
- Expired, malformed, or context-mismatched envelopes are not restored.

## Storage failure and recovery

- Browser storage writes return an explicit success or failure result.
- Quota, policy, privacy-mode, or other storage failures must never be described
  as saved or retained.
- While unsaved text exists, the unload guard remains active.
- The learner can copy or download a plain-text recovery copy before reloading,
  signing out, or leaving the page.
- If the server session is signed out but local cleanup fails, the UI says so
  explicitly and offers local-cleanup retry; it does not claim the session is
  still active.

Implementation: `apps/learner-web/app/lib/local-drafts.ts`,
`apps/learner-web/app/components/onboarding-form.tsx`,
`apps/learner-web/app/components/learner-runtime.tsx`, and
`apps/learner-web/app/components/sign-out-control.tsx`.
