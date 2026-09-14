# Reviewer and scanner release integration — 14 September 2026

The combined candidate includes the independently reviewed reviewer leaf
`5017faa139af6eee912029a2b7a58e69c6f4d41f`, the Saved calls browser correction
`35a136fb24d8200a2ce0d85475ecdd2ff1085691`, and scanner socket corrections
`8e6cfa94923a37242ca2e245d17c2daa80509cf6` /
`4fb2cbb5a5225164044e5f13fa888d3658afa198`.

Reviewer migration 0038 adds one table, `reviewer_auth_challenges`. All three
separately packaged backup/restore helpers now recognize its exact 93-table
`ac-postgres-parity-v18` contract. The explicitly allowed 0037 → 0038 rehearsal
preserves every existing row count and requires the new table to be empty.
Historical contracts remain unchanged. An independent Luna review found no
blockers in this addition.

The scanner wrapper bridges the pinned image's fixed `/tmp/clamd.sock` readiness
path to its configured shared socket. The observed installed release
`5c8b39249176b8030e7cca1d678c20ea7cb956ea` retains its exact pre-wrapper archive
shape and current health/socket/temp policy during canonical upgrade validation.
No live socket edit, database recovery or provider call was used.

## Validation

- Combined migration inventory, all versioned backup metadata and rate limits:
  **965 passed**, 35.52 seconds.
- Restore transitions: **78 passed**, two explicitly unavailable Docker/opt-in
  integration checks skipped.
- Scanner contract regressions: **102 passed**, 1.58 seconds.
- Scanner wrapper shell syntax passed on the actual Linux SSH host.
- Full Python lint and formatting passed (618 files); mypy passed (281 sources).
- The reviewer leaf's real production-Next browser proof passed invitations,
  browser-bound sign-in, three saved lenses, history, audio playback, revocation,
  separate logout and 1440/390/320-pixel layouts, using a fake mail delivery
  adapter. It does not establish live inbox delivery.
- Root applied pinned Prettier to the integrated reviewer sources. The existing
  browser packet's source hashes identify the original tested leaf above and
  remain preserved; formatting is not a new browser execution.

External receipts under `D:/AC-authority-closers-release-audit/activation-20260914/`:

| Receipt                              | SHA-256                                                          |
| ------------------------------------ | ---------------------------------------------------------------- |
| integrated-reviewer-parity-rates.xml | 1a001b4ce54a3dcf45196969638f38fcfc03e529cc88491ec7e976f5009e1500 |
| integrated-scanner-socket.xml        | 2a08b4e1d96fc12646b4f508828420105bd02dd85cd10e4d91056f1238c443c8 |

CI run 34798730242 failed before these fixes and produced no application image
bundle. A successful combined CI build and actual canonical deployments are
still required. This record makes no hosted readiness or production completion
claim.
