# Shared-read release test adapters

Candidate `c5e2893f7dda9f20095b62214ca7bc9df17aaaea` was not deployed.
Its exact application run `35802828218` found two stale test adapters after the
explicit `shared_identity_locks` option was added to acquisition reads.

The compiled browser fixture wrapped `AcquisitionReports.report` without
accepting the new keyword. The PostgreSQL claim/reservation lock-order fixture
wrapped `ConversationApplication.admit` with the same outdated signature.
Both adapters now accept and forward the option, preserving the application's
default exclusive mode. No runtime source or provider control changed.

Root verification after the adapter fixes:

- Compiled local guest upload, report, reload, claim and deletion browser test:
  one passed in 60.04 seconds, using local synthetic providers.
- Complete acquisition PostgreSQL file: 16 passed in 17.88 seconds, including
  both claim and reservation identity-lock-order cases.

The failed CI run is retained. A superseding frozen candidate must pass exact
CI and deployed staging playback/navigation acceptance before promotion.
Production and the existing fbe staging release remain unchanged at this
checkpoint. Additional paid provider calls: zero.
