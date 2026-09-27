# Google account recovery research boundary

The bounded AC Orchestra review inspected source
`2c45634657d0013fb1d7b5360d8168abd53a9083`. Its add-only handoff in the private
Authority Closers skills repository is commit
`3dc56e97e9ab29881d84c2760c044e1ecaa4e4ba`, preserving parent
`463c52a87ed2e87014f7cd88eabd36c169bff189`. Local retrieval verified the three
added paths, byte counts and hashes. The manifest SHA-256 is
`407b05b153bb048af0a79ba9754355b5fa6db1165e99b75c379513ad6b7ae67c`.

The review supports retaining canonical provider-key identity, signed OAuth
context and transaction types; preserving default rejection without valid new
acceptance; auditing actual consent supersession atomically; and keeping optional
profile claims separate from identity and phone verification. It ran no
application, database or browser tests. Its source review is not release evidence.

The proposed Terms-only acceptance with an age field omitted from a new event is
not accepted for the shared consent projection. That projection is also used by
learner eligibility. The implementation contract instead binds the existing full
canonical learner acknowledgement, including its explicit age declaration, to
the signed Google transaction. Legacy partial acceptance must not advance that
projection. Existing current consent must not have its timestamp rewritten or
have historical attestation evidence fabricated. This boundary was sent back to
the same Pro conversation for focused review.

The repository orchestration instruction was clarified to reuse source-pinned
Pro research for substantial design and component work while retaining local
review, integration, testing and release ownership. This documentation change
does not alter runtime behavior, grants, provider policy or production state.

Implementation tests and deployed behavior must be recorded separately against
the final code revision. Neither a completed handoff nor configured credentials
prove Google callback success, email delivery, SMS delivery or report quality.

## Full acknowledgement addendum

The same Pro conversation returned append-only commit
`d0842a800919ace718784c20dcfd13c6f885a01d`, preserving the previous handoff.
Its three added files, source pin and hashes were verified locally. The addendum
manifest SHA-256 is
`9360ecbde2ea6322be5b1897d0ee86b5bd7cbf0ea70081402fe703bfd1f82b43`.
It explicitly corrects the earlier Terms-only recommendation: a shared learner
consent projection requires the full acknowledgement to be captured and bound
to the identity operation. It also identifies the same missing challenge-bound
age declaration in new-account and first-mailbox-proof email OTP paths.

The accepted implementation direction is an additive, false-default challenge
field for email and signed-transaction acknowledgement for Google. Already
verified ordinary-user sign-in must not rewrite consent. A newly explicit full
acknowledgement can establish an actual present-time acceptance when prior
evidence is incomplete; it must never manufacture a historical timestamp.

A browser result enum and an existing session alone cannot prove that this
Google attempt succeeded. The accepted bounded design uses the already-signed
noncredential flow identifier plus a short-lived, signed HttpOnly receipt bound
to the actual issued session and surface. The same-origin completion endpoint
must verify that binding before the pending browser flow resumes. No session or
provider credential belongs in completion URLs or messages.

This addendum is source analysis, not executed software or browser evidence.
