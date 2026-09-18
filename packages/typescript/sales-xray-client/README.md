# Sales Xray presentation client

This is a thin browser client for AC's shared conversation domain. It introduces
no identities, tenant selectors, grants, storage, payment state or scoring policy.

`createEntryUrl({ origin, allowedOrigins, presentation, runId })` creates the same
run link for `standalone`, `lms`, `free-course` and `website` presentations. The
exact origin and allowlist must come from the application's approved deployment
configuration, never query parameters or a caller-supplied return URL. The
presentation changes entry context only; it does not authorize run access.

`loadCapabilities()` and `loadExample()` call same-origin
`/v1/conversation/capabilities` and `/v1/conversation/example`. The standalone app
may proxy these paths to an operator-configured, exact internal AC API origin.
The current client does not implement private-run retrieval or authenticated
mutations. A run deep link explains that boundary and labels the separate example.

`validateCheckpoint()` supports the native
`ac.sales-xray.signal-checkpoint/1` C1 export without rewriting its file. It
produces an in-memory view with source and feature fingerprints, original and
decoded sample rates, uncertified container synchronization, native windows/hops,
display strides, and null measurement gaps. No transcript is inferred from C1.
The optional `sales-xray-checkpoint.v1` UI interchange shape accepts a transcript
revision with source-bound segments and separate measurement profiles. It is not
a canonical server checkpoint or a release approval.

`createReviewProposal()` emits a data-only local proposal tied to run/checkpoint
and transcript revisions. It claims neither a reviewer identity nor submission.
Server assignment, authorization, stale-revision conflict detection, adjudication
and promotion remain AC API responsibilities.

`createMeasurementProposal()` supports acoustic-only C1 review without creating a
transcript. The caller must choose a concrete measurement series and point. Its
typed anchor retains the physical channel when present, decoded time, value or
null, unit, window/hop/display stride and feature revision. Source evidence records
whether the original audio fingerprint matched locally; it explicitly leaves
checkpoint authorship and feature-binary verification false. The export remains
an unsubmitted measurements-lane proposal with no attributed reviewer.

`assertCheckpointRevision()` rejects different normalized contents for an already
open run/checkpoint revision. A correction needs a new revision; it cannot replace
the existing local evidence under an unchanged identity.
