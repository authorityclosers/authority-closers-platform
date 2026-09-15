# Auth pending-verification and recovery UX

This learner auth cut makes the normal pending-verification journey actionable.
The public recovery response remains neutral. The combined backend change also
sends a canonical verification challenge when an eligible unverified password
account requests recovery; it does not mark an account verified or bypass email.

- `/verify-email` with no fragment token now presents a pending state: **Check
  your inbox**, with a clear fresh-link resend form. It no longer presents the
  missing-token error used for an invalid or expired token.
- A token that the verification API rejects still presents **Link unavailable**
  and retains the resend path.
- Password-recovery confirmation uses neutral delivery wording. It does not
  claim that every address receives a 30-minute reset link and links users who
  are still verifying a new account to the verification resend flow. No account
  existence or verification state is exposed.
- Existing course, activity, and bounded Sales continuation parameters remain
  validated and preserved in the verification link.

## Validation

- Candidate base: `d55e452424e0238b778aa156b4021462b2e03b70`.
- Focused auth suite: **16 tests passed** across verification and recovery
  continuity files under Node `24.19.0`.
- Extended auth suite: **120 tests passed** across password email continuity,
  recovery hydration, reset hydration, registration hydration, Sales auth
  continuity, and learner UI route checks under Node `24.19.0`.
- Learner TypeScript check passed.
- Scoped ESLint check passed with zero warnings.
- Prettier check and `git diff --check` passed.

The tests use synthetic API responses and do not claim provider delivery or
Google authorization. Backend delivery behavior and production deployment remain
owned by the release task.
