# One Sales Xray allowance across guest and account uploads

Guest use must carry into the existing Academy account when the visitor signs
in. The acquisition ledger previously counted guest claims and its own account
reservations, but did not include the existing authenticated upload ledger. A
person could therefore reserve work through both paths against separate totals.

The shared usage reader now includes all immutable visitor claims, acquisition
reservations and settlements, and the existing account's committed minutes.
Authenticated run admission also checks the combined total before queuing work.
Both paths use the existing canonical person lock; concurrent requests cannot
each spend the same remaining allowance. Confirmed no-work releases affect only
their own reservation. Uncertain provider work remains committed.

The limit is the user-requested 6,000 seconds. Existing explicit processing
entitlements and provider budget admission still apply. This change does not
grant provider access or create a second identity. It adds no migration or
manual production data edits.

## Verification

- Fifteen acquisition tests passed against a disposable PostgreSQL database in
  19.30 seconds, including mixed-path usage, claim continuity, confirmed release,
  and concurrent legacy/acquisition uploads.
- Ten existing conversation PostgreSQL tests passed in 16.76 seconds.
- Sixty-five application, entitlement and report projection unit tests passed.
- Scoped Ruff, formatting and mypy passed.

The local PostgreSQL harness created and dropped dedicated databases on the
existing loopback test server. No staging or production database was used.

## Integration boundary

This commit is separate from the frozen `8901ebb` release currently validating.
It is source and database-test evidence, not proof of hosted guest uploads.
The guest processing adapter remains to be mounted. Each resulting job must use
one charging path; copying a charge into both ledgers would double-count it.

The preceding `1ea2cb1` commit contains the user-approved free qualitative
overview projection. The Sales engine owner is implementing the separate
fourteen-part report structure supplied by Dipak.
