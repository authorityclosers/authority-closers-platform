# Email code and Sales Xray profile integration evidence

The email-code verification response now reports the canonical profile status.
First mailbox verification of an existing unverified registration provisions the
public Academy through the existing tenant service after checking the exact
consent revision. Already verified accounts retain their existing access.
Non-ASCII invalid consent revisions produce the normal neutral response instead
of a string-comparison exception.

Validation on 23 September 2026 used a disposable loopback PostgreSQL 18.6
schema, migrated through 0046, with the actual HTTP routes and domain services.
No email or inference provider was called. The combined password/email-code,
Sales Xray account journey and contact-profile suites passed 22 tests. The new
journey verifies account creation, tenant selection, required profile, CSRF and
revision failures, read-only bodyless eligibility, logout, repeat sign-in with
one identity and membership, and suspension denial. The unverified-account
reclaim regression also checks actual learner membership and workspace access.

The existing new-Google-subject concurrency test is synchronized at both absent
identity lookups so it exercises the intended race. Sequential callbacks may
legitimately both sign in to one canonical identity. The race test requires one
successful session, one conflict and no orphan identity. This targeted test
change was independently prepared as cf3f4015 and incorporated here.

Commands:

```text
python -m pytest tests/integration/test_password_identity_http_postgresql.py tests/integration/test_sales_xray_account_http_postgresql.py tests/integration/test_sales_xray_profile_postgresql.py -q --maxfail=1
python -m ruff check packages/python/ac_platform tests
python -m mypy packages/python/ac_platform
```

The PostgreSQL suite passed 22/22; Ruff and mypy previously passed for the
integrated profile source (307 Python source files). These are local integration
results, not proof of deployed OTP delivery, browser upload continuity, report
quality or production acceptance.
