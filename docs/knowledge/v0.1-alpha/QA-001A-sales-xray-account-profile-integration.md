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

## Worker admission checkpoint

The integrated worker change at `90b66b0c` resolves the actual customer through
the canonical acquisition usage/claim and checks the current verified contact
profile. It does not substitute the processing service identity. Fresh shared
row locks refresh ORM state and serialize profile writes across the provider
execution transaction. A pre-dispatch denial holds only the current job with an
audit event, preserving reservations, tasks and prior receipts. Run and
acquisition progress expose `execution_hold: account_profile_required` so the UI
can offer profile completion without restarting paid work.

On 23 September, six focused PostgreSQL tests passed in 106.99 seconds after
integration. They cover incomplete owner profile, stale identity-map refresh,
profile changes after the local/provider dispatch markers and unclaimed guest
work. Mypy passed for 308 source files; Ruff and `git diff --check` passed.

```text
python -m pytest tests/database/test_conversation_worker_postgresql.py tests/database/test_conversation_inference_postgresql.py tests/database/test_conversation_guest_ownership_postgresql.py -q -k "incomplete_contact_profile or profile_gate_refreshes or profile_change_after_local_marker or incomplete_profile_holds_provider or profile_change_after_dispatch_marker or unclaimed_guest_worker_holds" --maxfail=1 --basetemp <new-private-scratch-directory>
```

The native helper was built from the checked-out source with its source/binary
manifest before the passing run. Two earlier verification attempts exposed test
environment prerequisites: the default Windows temp ancestor was rejected by
the storage guard, and this new worktree initially had no native binary. The
passing run used a new private scratch directory and the verified native build;
neither protection was disabled.

After a dispatch marker, denial follows the uncertain/dead-letter path and
retains the in-flight reservation for explicit reconciliation. The local native
profile check is point-in-time: its transaction ends before the helper executes.
There is no automatic unhold, refund or retry. These local tests do not establish
live provider delivery, new report quality, mounted auth UI or production
acceptance. This checkpoint is not deployed.
