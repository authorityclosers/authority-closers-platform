# Release-owned learner consent profile

The learner UI names the reviewed version
`ac-learner-terms-privacy-2026-09-13-v1`. The staging release profile still selected
`staging-test-document-v1`, while production omitted the version entirely. The
installer intentionally clears ambient and Infisical consent values before
Compose evaluates the immutable profile, so configuring Infisical alone could
not resolve either mismatch.

Both source-owned environment profiles now bind the exact reviewed learner
version. The installer requires the consent key in both environments and checks
its exact value before Docker image loading or application mutation. Its
existing environment clearing remains intact, so external configuration cannot
silently substitute a different document version.

This is the initial held production release: production remains
`AC_EXTERNAL_SIDE_EFFECTS_HOLD=true`, `AC_EMAIL_PROVIDER=fake`, and practice
disabled. No tenant, identity, membership, capability, learner consent record,
provider activation, or production runtime change follows from this source edit.
Each learner must still perform the canonical consent-bearing registration
action. The parent's latest user-authorized production terms version supplies
the exact document binding; operator approval does not synthesize learner acts.

Validation:

- `uv run pytest tests/infra/test_application_release.py -q -k 'profile or release_consent' --tb=short --maxfail=1`
  passed: **27 passed, 56 deselected in 10.54 seconds**.
- The new source contract binds both profiles to the UI constant and retains
  the installer's removal of ambient consent values.
- Real profile-parser cases reject missing, stale staging-test, and unreviewed
  consent versions in both staging and production. Existing acceptance and
  malformed-profile tests remain passing, including the held production policy.
- Ruff, formatting, and scoped whitespace checks were completed after formatting.

Only the two profiles, installer profile contract, their existing test module,
and this evidence document are changed by this subtask. No staging, commit,
deployment, secret write, database action, or heavy build was performed here.
