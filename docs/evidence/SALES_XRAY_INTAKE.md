# Sales Xray local intake evidence

This evidence covers the local AC conversation intake boundary. It uses the
disposable loopback PostgreSQL harness and synthetic audio bytes. It does not
contact a provider, send a real recording, or change staging or production.

The intake contract keeps these steps separate:

1. Preparing an intake quote creates a server-owned recording, exact local
   permission evidence, and a bounded quote. It does not create consent.
2. Approval requires the quote fingerprint, privacy revision, and an explicit
   `accepted: true` value. The approval row is immutable.
3. Source upload requires the approved quote, the current owner/session, one
   bounded `Content-Length`, `application/octet-stream`, and the exact source
   byte count and digest.
4. A local run uses the approved `audioatlas-48000-v1` / `inspect_audioatlas`
   recipe, reserves the synthetic allowance atomically, and enqueues a local
   job with zero provider calls.

The PostgreSQL proof covers quote issuance versus consent, workspace scope and
owner checks, revocation and expiry, missing allowance rejection, replay and
conflicting idempotency keys, approval followed by private source storage and
local run enqueue, and database immutability for quotes, approvals, and
checkpoints. The transport unit proof verifies query scope, safe Origin,
content type, duplicate or missing length, zero bytes, transfer encoding, and
the configured body limit are rejected before authentication and before the
request body is read.

Validation completed locally on 13 September 2026:

- `tests/database/test_conversation_intake_postgresql.py`: **6 passed** in the
  approved disposable loopback PostgreSQL schema.
- `tests/unit/conversation_intelligence/test_intake_transport.py`: **7 passed**.
- Targeted Ruff, Ruff format, and Python compilation: passed.

Receipts are outside the repository:

- [intake PostgreSQL JUnit receipt](D:/Projects/authority-closers-release-transfer/2026-09-13-sales-xray/receipts/intake-postgres-junit.xml)
  — SHA-256 `BB9E91C7272304B9ED0DB656A27F6C1B454ACC15B3856A9A3FDA6A4046FCF2FE`.
- [intake PostgreSQL output log](D:/Projects/authority-closers-release-transfer/2026-09-13-sales-xray/receipts/intake-postgres.stdout.txt)
  — SHA-256 `1C6F5CD094183956EEEDEF04E4FBF32C1CEE62DA772EF173983707443B5889E6`.

The receipts prove a local test run only. They are not evidence of provider
activation, staging deployment, production deployment, or processing of a real
recording.
