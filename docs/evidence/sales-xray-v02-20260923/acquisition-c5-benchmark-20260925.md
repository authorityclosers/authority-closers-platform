# Owner-bound acquisition C5 comparison

An acquisition recording has a human owner and a separate processing principal.
The ordinary recording-stage endpoint cannot treat the human as that processor.
The new owner-authenticated quote/accept path resolves the existing submission
context and requires an exact, current, server-held C5 benchmark approval.

The bounded comparison retains the original C2 transcript, complete C4 facts and
previous report history. It selects only the approved saved OpenAI configuration
for one C5 request, without changing the global active provider configuration.
The source, owner, processing identity, lease, profile, prompt, language, pack,
configuration, token limit and allowance must all match. Client-supplied provider
or configuration fields are rejected. Quote and accept use distinct idempotency
keys, with replay preserving the existing job. Ordinary approval hashes retain
their old representation when the optional benchmark field is absent.

Validation:

- A focused PostgreSQL integration test passed in 43.85 seconds against the
  approved loopback disposable database, using an isolated scratch schema.
- The test covers an existing report, retained C2/C4, one fake OpenAI C5 run,
  unchanged active configuration, source/configuration/expiry rejection,
  same-tenant foreign-owner denial, accept replay and owner report retrieval.
- Ruff, Python compilation and targeted mypy passed for the owned changes.
- Independent source review found no blocker for this exact-source comparison.

This is a synthetic database/provider test, not a real OpenAI inference or a
quality comparison. Deployment and live comparison require separate receipts.
It does not prove Brain 3 coverage. The existing C5 cache identity still does not
distinguish every configuration-only change on the same provider/model; this
comparison changes Gemini to OpenAI and is tested to create a distinct run.
