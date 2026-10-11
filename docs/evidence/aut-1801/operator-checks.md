# AUT-1801: operator checks and evidence boundaries

Base source: `a5c71f8`. This strike does not deploy, merge, read protected
credential files or change production/staging data. Root/Claude and Browser
QA run the approved operations in their own injected runtimes.

## Recovery and speed

In each approved read-only runtime:

```sh
uv run python scripts/sales-xray-analysis-audit.py \
  --environment production --days 14 --output /private/new-production-audit.json
```

Use `staging` for its separate export. `AC_ENVIRONMENT` and
`AC_DATABASE_URL` must already be injected; never put their values in task
text. The script opens one read-only transaction and exports only IDs,
states, minute settlement kinds and timestamps. It refuses to overwrite
evidence and records truncation after 5,000 rows per collection.

Inspect the five historical held plans against their current minute events.
A held provider result can remain uncertain after #421 even when the
customer reservation has correctly been released. Only an unreleased exact
list needs the reviewed procedure in
`scripts/data-changes/RELEASE-FAILED-ANALYSIS-MINUTES.md`.
The tool uses the app's release path; it does not resend a provider request.

The timing summary separates completed stage runs, time before dispatch and
time from dispatch to receipt. Missing timestamps are excluded rather than
given zero latency. Retries and incomplete runs are counted separately.
C0/C1 share one local run; C3/C6 expose checkpoint timestamps. These measures
cannot establish the under-two-minute target for a ten-minute source without
duration-bound end-to-end evidence. The guest canary's observed intervals
are now attributed to the preceding observed stage; polling intervals still
limit their precision.

## QA account canary

Browser QA supplies its existing environment-specific QA identity and
password through runtime injection. Do not pass credentials as CLI flags,
print them or persist browser state. Production requires the QA operator's
explicit invocation:

```sh
ac-heavy uv run python scripts/sales-xray-account-smoke.py \
  --environment production --allow-production --browser
```

Staging uses `--environment staging --browser`. Run only after the owning
Coaching strike's `/v1/me/coaching/calls/{submission_id}` route is deployed.
No automatic schedule or production write is enabled by this change.

The run signs into the pinned official origin, uses the existing selected
workspace and uploads the committed known fictional canary clip. It verifies
the fixture digest and policy, accepts one bounded plan, and polls to delivery.
It never retries a held or uncertain provider send. The report must be bound
to the fixture. Call Coaching must match the submission, recording,
transcript, report revision, person and tenant and remain provisional.
Browser mode checks the real Report and Coaching views with no page errors.
Only a content-free receipt is printed. A passing guest canary alone does
not certify this account route or its deployed interface.

## Internal synthetic quality loop

The scorecard consumes the exact original 60 `audio_selected` manifest rows,
not generated fixture reports presented as pipeline results:

```sh
uv run python scripts/sales-xray-quality-scorecard.py \
  --dataset /home/acdev/datasets/synthetic-v1 \
  --reviews /private/staging-reviews \
  --output /private/new-scorecard.json
```

Without `--reviews`, it publishes honest readiness: all semantic criteria
remain unreviewed and pass rates are null. Counts are broken down by the six
pillars, language and business, plus Skills states, mistakes, next step,
outcome, per-call coaching and speaker roles.

Each review file is `<call_id>.json`, schema
`ac.sales-xray.synthetic-quality-review/1`, and names `environment: staging`,
`reference_basis: independent_answer_key`, a reviewer reference, recording
and report-run UUIDs, and source/response/answer-key SHA-256 digests.
`criteria` maps the documented criterion names to `verdict` (`pass`, `fail`,
`unreviewed`) and an inspectable `evidence_reference` for each reviewed verdict.
The current answer-key digest is checked. A supplied receipt remains an
artifact requiring operator verification against the actual staging run.

Root runs the owner-approved staging import/replay inside the dev AI budget.
Use transcript and CRM information available at the time of the call; hide
future outcomes and `fixture_truth` from providers. Verify the audio timing
before asserting playback alignment. Review against the independent key,
then aggregate. Re-score a new immutable output after each focused change.
This is internal assurance under AC-SVAL-01, never an official learner score
or synthetic validity claim. Provider/prompt activation belongs to Root's
AUT-1693 batch.

## Focused checks

Tests cover byte-level phone formats, actual PostgreSQL upload, read-only
inventory, exact dry-run binding, idempotent app release and audit attribution,
canary coaching shape, failed/missing timestamps, immutable staging review
bindings and QA HTTP failure cases without external calls. Web checks cover
the touched upload suites, lint, typecheck and production-build screenshots.
No full local test suite or live replay was run by this operator.

Results: combined focused HTTP/recovery/ledger/smoke/canary/timing/quality
checks passed 59 tests; the additional whole-batch rollback check passed.
The final speaker/map/service suites passed 83 tests, and the final
smoke/canary/quality suites passed 45. After the pinned native executable was
built, phone media, signals, canary atomicity and fixture checks passed all
75 without skips. Ruff formatting/lint and strict mypy passed for changed
Python sources. The frontend CI formatting failure was reproduced and fixed
in the four already touched upload files; no rendered behavior changed.
