# Published Practice Arcade and combined release recovery

The user's staging and production reconnect screenshots were traced by the
requested Luna testing lane. Authenticated practice sets and profile endpoints
returned HTTP 200. The published catalogue correctly reported `mode: published`
and `responses_stored: true`, while the learner decoder accepted only editorial
preview mode with storage disabled. Valid published data therefore became a
client parsing error and the misleading reconnect screen.

Accepted source `2b4b16e` now decodes the two explicit catalogue variants. Preview
still requires storage false; published mode requires storage true. Individual
set snapshots accept the same two modes. A mismatched catalogue is rejected.
No server state or user progress is changed by the fix.

The Luna lane reported 103 relevant tests, typecheck, lint and formatting passed.
The combined root additionally ran all four new decoder tests and learner
typecheck successfully after cherry-picking the fix as `e3f6823`.

## Current combined candidate

The failed `8901ebb` application CI run was not deployed. Its 15 migration parity
failures were repaired in `c983172`; see `20260914_ACQUISITION_RESTORE_PARITY.md`.
The candidate also merges the approved full free overview projection and shared
guest/account allowance from `8004d4a`. On the combined source:

- All Python lint and formatting pass; mypy passes 265 source files.
- 65 focused application, entitlement and projection tests pass.
- 15 acquisition PostgreSQL cases pass in 16.82 seconds in a disposable database.
- 897 restore/parity/registry checks pass, with two Docker-dependent skips.
- The learner decoder and typecheck pass as above.

Both core deployments still run `69db2257`; the standalone staging frontend runs
`99cdee5e`. The hosted testing lane confirms intake and provider processing are
disabled, with no installed activation descriptor or dedicated worker. It made
no external provider calls and spent nothing. Source validation is not a claim
that the new interface or upload processing is live.

Google's signed-in project console now shows the OAuth app audience as
In production. Production privacy/terms URLs were saved; both exact Sales
callback URLs were already registered. The staging Google account picker loaded,
but Chrome blocked the return with ERR_BLOCKED_BY_CLIENT, so hosted sign-in is
not accepted as passing. Staging routing itself has a separate successful
before/after receipt, preserving every prior Cloudflare ingress entry.

The superseded GitHub core transport artifact was removed only after the source
bundle verifier accepted its preserved offline copy, freeing the bounded
artifact pool for this replacement. Provenance and hashes remain outside Git in
`D:/AC-authority-closers-release-audit/core-99cdee5-artifact-preservation.json`.

Next: the single corrected combined CI run, immutable images, source-owned
staging installation, hosted activation proof, and production promotion.
