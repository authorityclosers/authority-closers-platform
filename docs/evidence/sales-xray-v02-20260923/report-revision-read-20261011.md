# Optional retained Report revision — AUT-1677

The Report envelope codec accepts the planned optional lowercase SHA-256 `report_revision`. Omission keeps older reports and their output shape unchanged. The saved-call preload preserves a present valid digest and checks it against the per-call Coaching revision; a changed Coaching revision leaves the retained Report ready without that bootstrap. Invalid native source, identity or a malformed present digest still produces the helper's bounded unavailable state.

Validation: 92 focused envelope/preload/Coaching codec cases pass (91 in the initial batch and the additional malformed-digest preload case); app typecheck, changed-file ESLint and Prettier pass. No UI, live approval, provider, schema or write permission changed.

Server admission remains with Strike C/Root: add the digest only after final withholding, using `content_hash(envelope["report"])`. Never compare to raw C5 or a pre-withholding digest. Strike A must pass the returned `reportRevision` alongside the ready result. The per-call Coaching backend merged as bcd4e40 already computes the same projected-report digest; this reader preparation does not claim the acquisition endpoint emits the new field yet.
