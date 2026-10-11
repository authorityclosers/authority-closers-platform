# AUT-1801: bounded operator checks and evidence

Original base: `a5c71f8`. Historical head:
`6ad308dcaac0657c050d0fcc24dea302cb5c8146`.
AUT-1807 revision 1 bounds PR #443 to phone intake, provisional speaker
prediction, QA-account Report/Coaching smoke and guest-canary checks, with
their tests. This operator does not merge, deploy, activate providers or
change production/staging data. Current repository review controls apply:
green revised-head checks, fresh exact-head CTO review, then CEO approval;
the watchdog waits for green main. Historical approval does not cover this
correction.

## QA account journey

Browser QA supplies its held environment-specific identity and password
through runtime injection. Never pass credentials as CLI flags, print them
or persist browser state. Only the authorized QA operator invokes:

```sh
ac-heavy uv run python scripts/sales-xray-account-smoke.py \
  --environment production --allow-production --browser
```

Staging uses `--environment staging --browser`. Verify deployment of
`/v1/me/coaching/calls/{submission_id}` first. No automatic schedule or
production write by this strike operator is enabled.

The smoke signs into the pinned official origin, uses the selected workspace
and uploads one committed fictional canary clip. It verifies fixture digest
and policy, accepts one bounded plan and polls to delivery. It never retries
a held or uncertain provider send. Report must bind the requested submission,
upload acknowledgement's recording, fixture digest and valid report-run UUID.
Per-call Coaching must bind submission, recording, transcript, report
revision, person and tenant and remain provisional. Browser mode verifies
Report and Coaching are visible with no page errors. Only a content-free
receipt is printed; a guest-canary pass does not certify this account journey.

Expected failures return a fixed safe code and, after upload, the submission
UUID. Response bodies and exception contents are discarded. Inspect that
original call rather than uploading again or retrying an uncertain send.

The guest canary checks paired next-call focus/practice or explicit absence
of an improvement. Observed time belongs to the preceding stage; polling
limits precision. This does not measure full upload-to-UI latency.

## Retained behavior and dev check

On `/analysis/new`, select an AMR, AWB, AAC, 3GA, WebM or Opus recording;
selection remains valid through the existing consent/admission flow. The
server validates bytes, keeps the original source binding and rejects
non-audio. Fictional media and PostgreSQL HTTP regressions are retained.

Speaker prediction recognizes bounded English/Hindi/Marathi introductions.
Buyer questions and incidental team/location mentions do not reverse roles.
Conflicting introductions and extra voices remain unresolved. Predictions
are provisional, not identity or confirmed role measurements. The local
60-text diagnostic used ideal diarization and repeated synthetic scaffolding;
it does not establish real-call accuracy or semantic report quality.

## Deferred units and open acceptance

The new audit exporter, prepared minute-release operator and scorecard
aggregator are omitted as complete implementation/test units. Their exact
nine files remain at the historical head above; a byte-verified private copy
and SHA-256 manifest are in the strike's `deferred/6ad308d/receipt.json`.
No retained source imports those units. They are preserved evidence under
AUT-1801, not executable procedures in this revised PR.

Root's existing source evidence queue owns recovery/timings. Read back the
five historical held plans and current reservation journals before concluding
recovery failed. A held provider result can remain uncertain while #421
correctly releases minutes. Existing merged #421 remains the app recovery
and minute authority. No current export demonstrates a need for an apply;
owner-approved change safeguards remain binding.

Speed acceptance needs current fourteen-day staging/production stage, queue,
provider and retry clocks, bound to measured source duration. For 9–11-minute
sources, distinguish strictly under 120 seconds from the boundary. Missing
clocks do not count as zero latency. Source reservation and plan acceptance
exclude earlier work; neither alone proves full upload-to-UI speed.

Independent semantic review uses AUT-1680 and AUT-1686 intake. Preserved
private source receipts pin five canonical eligible recordings (1,073.318
seconds), while the full 60-call canonical replay remains unavailable.
Independent staging reviews are zero; semantic pass rates remain unknown.
Recheck audio/timing/transcript/key hashes before an authorized replay within
the dev AI budget. Hide future outcomes and fixture truth from providers.
Use independently reviewed report/Coaching receipts; never substitute answer
keys as pipeline output. Internal assurance is not official AC-SVAL scoring.
Provider/prompt activation stays with Root's AUT-1693 batch.

Production acceptance remains open: current five-plan/minute read-back,
duration-bound timings and Browser QA's bound Report/Coaching API/UI receipt.
Production-version closure belongs to the release engine.

## Historical versus revised-head verification

Historical `6ad308d` CI was green. Earlier notes include focused tests for
both retained and now-deferred tools; those aggregate counts do not describe
the revised head. The four earlier phone screenshots came from a local
production build and remain historical evidence.

The corrective SHA, additions plus deletions against pinned current main,
actual focused test commands/results and shared `127.0.0.1:3026` preview
receipt are recorded separately in `/home/acdev/strikes/1801/NOTES.md` and
PR #443. Reuse no historical result as a revised-head or deployed pass.
Live account, recovery, speed and semantic-quality claims remain unverified
until their authorized receipts arrive.
