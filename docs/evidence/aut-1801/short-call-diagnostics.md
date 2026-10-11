# AUT-1801: short-call local inspection and safe failure categories

The C0/C1 decoder has no 25-second minimum. The focused database regression
publishes real decoded C1 for a 25-second fictional waveform and verifies its
source digest, measured duration and native feature rows. It covers both the
48 kHz offline worker and 16 kHz hosted-worker path, with real native extraction
and a local helper-transport double; it supplies no hosted confinement receipt.
It does not explain
the owner's e94ef127 failure; that exact hosted failure remains unverified.

Local worker failure now appends `conversation.local_failure_observed` with
`ac.sales-xray.local-failure/1`, a fixed phase (`local_inspection` or `erasure`),
allowlisted native/signal category, attempt count and recovery generation.
Arbitrary exception/decoder output never enters audit or operational output.
The phase covers C0/C1 together rather than guessing which operation failed.
Existing durable job failure and provider/customer reservation handling stay
under their existing recovery paths.

Claude/Root can inspect the bound job's audit category and the native operation
status for e94ef127. Missing metadata cannot justify a new duration refusal or
an uncertain-effect retry. Tests verify retained native categories, discard
arbitrary/mutated strings and exercise the database failure path.
