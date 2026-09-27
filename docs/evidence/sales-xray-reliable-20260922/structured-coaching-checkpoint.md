# Structured coaching generation checkpoint

This supersedes the fresh-account status in `staging-819a-acceptance.md`; that
earlier deployment and browser checkpoint remains unchanged.

A newly authorized fictional price-objection account call on staging completed
transcription and fact extraction, then paused during coaching validation. The
provider returned a complete JSON response but omitted root `objection_analysis`
and `closing_analysis`, nested closing material in the overview, and omitted
`overview.missed_details`. Its returned-response receipt and source-bound input
were inspected read-only. No additional provider request or database repair was
performed during diagnosis. The old response cannot be made complete by adding
unsupported empty findings. Production was not promoted.

New detailed Gemini Flash requests use a versioned native request envelope with
`generationConfig.responseJsonSchema`. It requires the existing report sections,
closes objects, constrains evidence references and overview fields, and excludes
server-derived metadata. Existing literal-source, semantic, publication and
cross-reference validators remain authoritative. The saved v1 request envelope
still reconstructs without changing its bytes. C4, standard reports and the
smaller Gemini Pro route preserve their prior envelopes.

The schema consumes the existing input allowance. The full 64-fact regression
therefore uses the already-supported 8,000-output extended lane; the exact old
1,800-output v1 request still replays, while a new schema-bearing request that
exceeds the smaller allowance is refused. No source turns or facts are removed.

Validation at this checkpoint: 1,089 conversation unit tests passed; one test
requiring POSIX ownership was explicitly skipped on Windows. An actual retained
v1 request and response were also revalidated locally with zero provider calls
and zero database writes. Its report digest remained
`7928e22cee854cb5b5e17568dd7c582517f75383e8273853555bb16480442fb1`.
The structured-generation change still requires exact-release CI and a fresh
live staging response; offline schema tests do not prove provider acceptance.

The owner subsequently requested complex calls as long as 60 minutes, within
the separately approved INR 1,000 total recovery-test ceiling. Duration
approvals, stereo working space, complete-transcript input size and a varied
fictional hour-long fixture are being checked before that paid test. This
checkpoint does not assert that hour-long processing or production acceptance
has passed.

Provider contract checked against the official
[GenerateContent API reference](https://ai.google.dev/api/generate-content).
