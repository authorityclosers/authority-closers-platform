# Email sign-in integration regression

Base: `7ff3581fc39f616d189c525c2d6b3e23a51e472a` (all three handoff branches merged).

The failing age-attestation test queried `PasswordCredential` by a person UUID even though its primary key is the credential UUID. PostgreSQL reproduction confirmed that this was not evidence of deleted credentials. The test now proves that the existing credential is persisted before verification and that its identity and password hash remain unchanged after the ineligible challenge is rejected. Two removal checks elsewhere in the same suite now query the actual `person_id` column, preventing false passes.

With that lookup corrected, the test exposed a separate response-metadata issue: an already verified sign-in with no new consent returned previous-consent audit fields despite `consent_audit_required=False`. The service now includes those fields only for first mailbox verification. Stored consent history, age eligibility, credential reclamation and session behavior are unchanged.

Validation on disposable PostgreSQL 18.6 with synthetic fixtures only:

- Original test: failed at the incorrect credential primary-key lookup.
- Corrected lookup before service change: failed at unexpected prior-consent metadata, while credential-preservation assertions passed.
- Complete `tests/integration/test_password_identity_http_postgresql.py`: **20 passed** after the change (`PGTZ=UTC`). This includes verification, credential/session reclaim, privilege denial and concurrent Google registration.
- Ruff, focused mypy and `git diff --check`: passed.

No email/provider call, production database change or deployment was performed. This test result is not proof of production email delivery or Google console configuration.
