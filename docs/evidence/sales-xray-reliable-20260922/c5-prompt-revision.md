# C5 prompt revision evidence

Date: 2026-09-23

The C5 semantic wording guard is versioned through `coaching_prompt_revision`.
Legacy requests use `coaching-v1`, omit the field from serialized `StageRequest`
and `PlanManifest` values, retain the existing `qualitative-coaching-v1` recipe,
and produce the existing provider payload and input digest. New processing-plan
quotes select `coaching-v2`; the revision is carried into the derived C5 request,
the C5 checkpoint configuration, and the provider payload digest. The C4 request
rejects a coaching revision.

The v2 instruction requires an explicit source-recorded rejection before using
“declined” or “refused”. A discussed possibility is not an offer, and missing
acceptance, authorization or booking is not rejection; when the source does not
establish a decision, the report must say it is not established in the call.

Retained C5 recovery reads the saved request revision with the same bounded
legacy default and passes it into prompt reconstruction when the historical
provider bytes are not supplied. The historical-byte path remains authoritative
and unchanged.

Focused tests cover byte-stable legacy serialization and payload hashing,
legacy checkpoint cache identity, distinct v2 payload identity, manifest/request
round-tripping, derived-request revision pinning, and C4 rejection of the C5
revision.

Validation on the local synthetic transcript and fact packet:

```text
python -m pytest tests/unit/conversation_intelligence/test_c5_prompt_revision.py \
  tests/unit/conversation_intelligence/test_processing_plan.py \
  tests/unit/conversation_intelligence/test_report_language_contract.py \
  tests/unit/conversation_intelligence/test_inference_tasks.py \
  tests/unit/conversation_intelligence/test_extended_coaching_budget.py \
  tests/unit/conversation_intelligence/test_reports.py -q
111 passed

python -m pytest tests/unit/conversation_intelligence/test_retained_c5_recovery.py \
  tests/unit/conversation_intelligence/test_c5_prompt_revision.py -q
14 passed
```

The disposable PostgreSQL recovery harness was also run with both persisted
request shapes (`coaching-v1` omitted and `coaching-v2` present):

```text
test_conversation_retained_c5_recovery_real_postgres
2 passed in 13.29s
```

Root validation also passed 22 focused waveform, revision and retained-recovery
unit tests, Ruff format/check for all 688 Python source/test files, and Mypy for
302 source files. The earlier whole conversation unit run passed 1,158 tests
with one POSIX ownership skip before the final reconstruction regressions.

Independent review found no remaining P1/P2 in the revision path. The existing
Admin limitation for reconstructing automatic repair requests is separate:
their exact historical request bytes remain supported through the private
retained-recovery CLI.

No provider calls, operational database writes, deployment actions, customer
data or fixture-specific wording were used. The PostgreSQL result used only its
disposable per-test schema and synthetic recovery rows.

The combined PostgreSQL run also exposed a test-only identity collision: the v2
retained seed and the guest HTTP seed both promoted different synthetic people
to the same globally unique `dipak@authorityclosers.com` control email. The v2
seed now uses the separately allowlisted `suyash@authorityclosers.com`; the
guest seed remains unchanged. Rechecks passed independently:

```text
test_retained_c5_recovery_http_admin_and_acquisition_reads: 1 passed in 13.18s
test_retained_c5_recovery_real_postgres (coaching-v1, coaching-v2): 2 passed in 12.20s
```

Root then ran the complete retained-recovery file together: **3 passed in
14.50s**, proving the distinct identities coexist in the shared disposable
schema. The other 25 cases in the broader seven-suite run had already passed;
the two parametrized cases also passed in that run. No constraints were disabled.
