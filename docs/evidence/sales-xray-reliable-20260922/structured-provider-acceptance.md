# Structured provider request acceptance

Staging release `bd198214` activated approved provider revision 3, preserving the
owner's INR 1,000 total synthetic recovery-testing ceiling. The saved short
account call reused its completed C2 and C4 work. Its new C5 request paused with
`conversation_provider_dispatch_failed`; no report or successful provider
receipt was produced. Production was not changed.

The child broker had collapsed allowlisted provider HTTP errors into a generic
failure. It now preserves only existing safe codes; unknown text and multiple
exception arguments remain redacted. No provider error body crosses that boundary.

Three separate fixed fictional probes used the existing scoped Gemini identity,
each reserving a maximum of INR 1 before its only dispatch, with an exclusive,
fsynced private journal. No customer recording was sent and no retry occurred
inside a probe. These three maxima count against the same owner testing ceiling;
the independent journals do not themselves enforce a cumulative project cap.

- Original v2 schema SHA-256
  `cf738359daf55c908b5e0ab664761fd0339f2043583d3a3e17ac85fd07b81cf1`:
  HTTP 400 `INVALID_ARGUMENT` twice. The provider supplied no more specific
  classification; raw remote messages and secrets were not retained.
- Removing only `minItems`, `maxItems`, `minimum` and `maximum` produced schema
  `aad4ed620fa69ebb51a6fe91b0fd34a1a3a28aed6fd85e21cf10d6c77718a907` and HTTP 200.
  All object shapes, required fields, enums, references, null branches and
  additional-property restrictions stayed unchanged.
- The successful probe deliberately had a 256-token output cap and finished
  `MAX_TOKENS`: it demonstrates request acceptance, not a valid coaching report.

New detailed Flash tasks use the `gemini-json-v3` marker with this generation
schema. The report parser still enforces numeric bounds, cardinality, source
evidence and semantic rules. No parser or professional-review gate was relaxed.
Retained v1 and v2 payloads retain their original markers and schemas; changing
only a marker or schema is rejected. The old v2 canonical schema hash is tested.

The [Gemini API reference](https://ai.google.dev/api/generate-content) lists the
used JSON-schema features, while the [structured-output guide](https://ai.google.dev/gemini-api/docs/generate-content/structured-output)
warns that complex schemas can be rejected. The isolated probes demonstrate
that the numeric constraints in combination caused this request rejection;
they do not identify one individual offending keyword.

Validation: 1,141 conversation unit tests passed, with one Windows/POSIX
ownership skip; 78 focused schema/adapter/probe and 32 long-context/mixed-script
checks passed. Ruff lint/format and mypy (302 source files) passed. Exact-release
CI and staging report acceptance are recorded separately as they complete. The hour-long recording has passed native processing but has not yet
been submitted to the live AI stages. Its Terms/test approval is recorded.

Private probe receipts are under
`D:/AuthorityClosers-Private/sales-xray-reliable-20260922/schema-probe-*.json`.
Failed short recovery run: `c38a3afc-cfa5-4d5c-bb18-4a3de8d36599`, INR 22 ceiling
retained as uncertain. Prior two synthetic calls have six dispatched tasks
totalling INR 42 in request ceilings. With the three INR 1 probes, the recovery
tests so far have INR 67 in dispatched maximum exposure, not an invoice total.
