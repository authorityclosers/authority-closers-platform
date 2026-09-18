# Windows release-test isolation

Date: 2026-09-13. Isolated branch `codex/windows-test-environment-20260913`,
based on combined release `7da7200ece2c1a25cb95e4ee47f30ec53218f0ba`.
Only two test files and this evidence document change. Production code, process
security, environment allowlists and validation assertions remain intact.

## Reproduced environment pollution

The release owner's full unit run had 3,633 passes, 17 failures and one skip.
Several later Windows subprocess and cryptographic tests failed together. Its
fresh-process subset passed the original RSA/import/runtime failures, indicating
an ordering-dependent harness problem.

`test_child_reads_only_the_exact_provider_credential_and_returns_raw_frame`
called the disposable child entry `_child_execute` inside the pytest process.
That entry intentionally removes credentials and non-allowlisted environment
names before invoking an adapter. The test's three `monkeypatch.setenv` calls
restored only those three names; the remaining real process environment was
left scrubbed.

The ordered two-test reproduction ran that broker test followed by
`test_pinned_google_auth_verifies_real_rsa_signature_audience_issuer_and_expiry`.
Before the fix it produced one pass and one failure with the same OpenSSL entropy
initialization error. After the fix the identical pair passed in 1.49 seconds.
Receipts in the recovery packet are `windows-env-ordered-red.log` and
`windows-env-ordered-green.log`.

The test now installs a detached synthetic `os.environ` mapping inside
`monkeypatch.context()`. Child credential consumption and scrubbing are still
asserted inside that context. Afterward the original environment object and key
set must be restored. The original adapter credential, body and output checks
remain. Actual host environment values are neither copied into fixtures nor
printed. Independent Luna review found no blocking issue.

## Independent SQLite registration defect

Fresh subset collection also exposed two identity-hardening test setup failures:
`activity_progress` was registered in shared SQLAlchemy metadata while its
`enrollments` dependency was absent. Both test schema setup calls now use the
existing canonical `model_metadata()` registry before `create_all`, making their
setup independent of unrelated test collection. The exact two cases and the full
11-case hardening module passed in isolation. No database or production model
behavior changes.

## Final bounded validation

With the complete broker module first, the Google identity module, identity
hardening module, four real media subprocess-lock cases, two launcher environment
cases and the Windows runtime bootstrap module passed **63 tests in 58.21
seconds**. Receipt: `windows-env-ordered-subprocess-final.log`. This uses Python
3.12 from the existing local environment with `PYTHONPATH` explicitly bound to
the isolated source tree. Ruff, formatting and diff whitespace checks pass.

No full-suite rerun was duplicated; the release owner retains that check after
integration. Targeted mypy on the pre-existing hardening test file reports two
existing `_PrivacyBatchHook.apply` protocol signature mismatches; these are
unchanged and outside production mypy scope. No check is disabled or weakened.
