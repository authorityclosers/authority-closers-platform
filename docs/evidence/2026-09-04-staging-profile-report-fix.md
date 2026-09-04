# Environment-neutral application release status evidence

Date: 2026-09-04

## Scope

`install-application-release.sh` now derives its final status from the exact
environment profile installed with the release. It validates the complete
profile as canonical LF text with safe, non-empty, exactly-once assignments,
requires every key needed by the release, and rejects missing or malformed
entries before image loading, Docker Compose commands, or application
database/service mutation. Only the reviewed non-secret profile keys are
admitted. Compose receives the profile-derived project through explicit
`--project-name`, with ambient project/file/profile controls removed, so the
profile's policy and provider values are the effective values at runtime.

The installer classifies `AC_EXTERNAL_SIDE_EFFECTS_HOLD` as either `held` or
`released` and accepts only the reviewed `fake` or `resend` provider names.

The final line reports only non-secret release metadata:

```text
PASS  <environment> now runs exact release <release-id> (external side effects: <held|released>; email provider: <fake|resend>).
```

It does not print provider credentials, sender addresses, OAuth values, or any
other Infisical secret. The same logic applies to staging and production; it
checks each target against its own reviewed environment contract. The reviewed
staging profile therefore reports `released` with provider `resend`, while the
reviewed production profile reports `held` with provider `fake`.

This change is implementation/test evidence only. No staging or production
deployment was run, and no production state was changed.

## Verification

Focused and repository validations are recorded below after execution:

```text
uv run pytest tests/infra/test_application_release.py -q
46 passed in 8.68s

uv run pytest tests/infra/test_application_release_archive.py -q
40 passed in 11.05s

uv run pytest tests/infra -q
175 passed, 10 skipped in 38.21s

uv run pytest -q
1113 passed, 130 skipped, 1 warning in 152.99s (0:02:32)

Bash syntax checks (install-application-release.sh and test-release-install.sh)
passed via Git Bash. The full `test-release-install.sh` integration probe
requires POSIX ownership semantics and was not runnable in this Windows
workspace; it failed before exercising the changed installer with an OS
permission error.

git diff --check
passed

uv run ruff check tests/infra/test_application_release.py
All checks passed
```
