# Google acquisition fixture verification — 2026-09-24

The focused PostgreSQL test now uses the current Sales Xray completion contract: Google start requires a synthetic `/auth/complete?flow=<UUID>` return path, and callback redirects carry that same flow with `auth_result=success` or `auth_result=failed`. The success case also checks that the signed completion receipt matches the correct flow and rejects a different flow.

The test covers missing age attestation as an authentication-only attempt that fails without creating a `Person`, and full current acknowledgement as registration. It preserves assertions for one canonical learner, selected learner tenant and role, and guest usage retained after claim.

Validation: the two parameterized cases passed against the disposable local PostgreSQL test database (`2 passed in 19.22s`). Ruff check passed for the changed test. An earlier attempt with the obsolete return path and 401 expectation failed; that fixture trace is superseded by the corrected test and is not a product callback failure.
