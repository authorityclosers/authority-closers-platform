# AUT-348: dormant v7 output validation and storage

Source baseline: `a0d537cf3c72a7734a18cbe7d913864f9254e7bd`.
Controlled sources: AUT-341 plan and decision brief; the AUT-348 spec, D8 amendment
and ETH-03 addition. Fixtures use the checked-in fictional LumaBoard canary only.

The C5 parser applies B1's amended call-map checks, checks prose for provider
speaker labels and requires a source-bound ethics note for an unverifiable claim.
Validated call purpose, prospect facts, literal/null next-step wording, answer fit,
seller tasks and objections survive the stored-draft integrity/read path exactly.

The 24 D8 controls cover each of six states with 0/1/2/3 valid distinct refs across
all eight dimensions. Observed produces eight downgrades for 0 refs, eight for
1 ref, and none for 2 or 3 refs. Partial produces eight downgrades for 0 refs;
other controls produce none. Duplicate refs count once. Not-applicable, conflicted
and unknown pass through. Invalid segment IDs and copied quotes fail validation
before counting. These structural checks do not prove semantic entailment.

All 12 B1 failure codes survive worker/progress allowlists and create exactly one
repair intent; an already-repaired request creates none. The route's existing
repair budget and OpenAI no-repair rule are retained.

ETH-03 drops invalid entries with only a count. Generation appends valid model
marks with `reason_ref=coaching-v7:sensitive_segments`, alongside detector hits;
replays and operator releases retain their existing precedence. No external
provider, customer recording, live database, migration or runtime gate is used.
The generation-store argument and finish-time forwarding are the two necessary
same-task file additions to the original allowed-file list.

Legacy fixture hashes captured before editing:

- v4: `97d29ec397fc3fcd57a36802d6ca88b9d1549cb03287d6e70349afc00d874fd8`
- v5/v6: `2a2056a560191a13280483c05434315820e2cff1e7095ebfacefd67b3082b77e`

Unset call-map and sensitive-segment fields are omitted. Prompt/schema snapshots
and runtime refusal remain covered by the existing v7 prompt/v6 integration tests.

Initial verification: focused Python output suite 60 passed; focused web report,
call-map and processing-copy suites 124 passed. Full required checks follow before
PR handoff. Dev verification is offline as specified; v7 remains unavailable to
real calls before Gate 2 and the AUT-504 prerequisite.
