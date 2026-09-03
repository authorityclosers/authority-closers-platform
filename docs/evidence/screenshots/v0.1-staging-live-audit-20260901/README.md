# v0.1 staging baseline audit — contextual captures

Captured: 2026-09-01

These three sanitized screenshots document the pre-candidate staging baseline
that motivated ADR 0028 and the learner UI repair. They show only public auth
and catalog surfaces and contain no learner email address, password, provider
token, session token, OAuth transaction value, or secret.

They are **contextual audit inputs, not release-bound implementation
evidence**. The capture did not record a complete immutable commit SHA,
container digest, configuration fingerprint, or authenticated actor. Nothing
in this directory proves the current candidate, an exact staging deployment,
Google OAuth completion, email delivery, learner provisioning, enrollment,
progress mutation, or production readiness.

Files:

- `01-login-desktop.png` — public learner login baseline.
- `02-register-desktop.png` — public learner registration baseline.
- `03-public-course-desktop.png` — published course detail baseline.

Exact-current evidence must be captured into a new release-specific directory
after deployment and must include the full commit SHA, deployment identity,
environment/configuration boundary, sanitized actor description, viewport,
route/state, reproduction steps, and pass/fail result.
