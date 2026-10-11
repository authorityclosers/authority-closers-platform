# Strike C — authored synthetic sandbox import

Owner continuation: AUT-1676 / PR #437. The sole staging target is AC Sandbox
`90ec1979-0d85-4829-ba8d-cabde2a9a9d3`; Claude is the named importer. This source
does not apply staging data, change services, deploy or merge.

## Authority and storage

An immutable organisation-registry flag explicitly opts in the sandbox. A name,
an uploader-supplied flag or a real organisation does not grant sandbox authority.
Existing cookie, selected-tenant, current owner/admin, session, origin and write
profile gates apply. Production does not register these routes.

Migration `20261011_0082`, following C's `20261011_0081`, stores the explicit flag
and authored synthetic revisions. All three backup/restore consumers include them
under parity v53. The new registry tables stay separate from real call acquisition,
minute accounts, provider tasks and payment state. Fake people and invoices never
create canonical identities or financial entries. Changed content supersedes a
revision instead of replacing it; update/delete triggers preserve history.

The full bundle preserves metadata, estimated transcript, six report pillars,
answer key and six coaching sections. Report/coaching sections must match the
authored answer key exactly. Reports are delivered as `authored_report`, `done`,
with no minute state or AI run. Read responses omit answer-key future truth;
coaching, skills and missions remain private to the importing person.

## Published data input

Consume Strike F's `/home/acdev/datasets/synthetic-v1/schemas/import-bundle-1.md`,
`import_ready/index.json`, each exact indexed folder, `world/`, multi-year call
summaries and `simulation/operations/`. Immutable synthetic keys preserve business,
rep, company, prospect, deal and call lineage. Undated master entities use the
published simulation start; explicit calendar dates use F's IST timezone.

The current export has 3,360 full bundles, 177,615 volume call summaries and
875,550 master/history records across ten fictional sellers. Individual records,
full-call bundles and actual request batches are validated before an HTTP session
is opened. Duplicate identities across batches are refused. The CLI pins all
authored content with a rolling SHA256 and rechecks it during apply.

Each request has at most 128 records and stays below the existing 1 MiB middleware
cap. Source hashes/revisions make restarts and repeats safe. Atomic conflicting
batches roll back completely. Current bundles have `audio_file: null`: the export
has no timing-verified audio. Text imports cannot claim playable audio. Verified
audio requires the separate exact-media handoff; no external call is made here.

## API for integration

Prefix: `/v1/conversation/acquisition/imports/sandbox`.

- `POST /calls`: `synthetic-call-bundle/1`, with Idempotency-Key.
- `POST /records`: `synthetic-record-batch/1`, with Idempotency-Key.
- `GET` prefix: selected sandbox ID, counts and authored date range by kind.
- `GET /records/{kind}`: up to 100 current revisions and an optional next_cursor.
- `GET /records/{kind}/after/{cursor}`: exact key pagination.
- `GET /calls/{call_id}`: metadata, transcript and authored report.
- `GET /calls/{call_id}/coaching`: private authored coaching.

Kinds include world, business_history, people, companies, contacts, leads, deals,
invoices, payments, calendar, people_events, rep_weeks, sales_events, skills,
missions, call_summary and full call reads. Path selectors retain the existing
guard's strict query policy. Every response explicitly marks synthetic data.
Strike A/B/D/Admin must consume this separate sandbox read contract; their pages
and renderers are not changed in this strike.

## Operator path

After reviewed migration/runtime integration, the named staging operator uses
`scripts/data-changes/enable-synthetic-sandbox.py`, dry-run by default, with the
recorded approval reference and approving owner person ID. It requires the exact
active AC Sandbox target and owner, uses one transaction, reports before/after and
audits each apply. It refuses all other environments. Retain the snapshot, dry-run,
run ID and read-back on the issue. No operator run was performed here.

Dry-run the corpus through `uv run python -m
ac_platform.conversation_intelligence.synthetic_import_cli --dataset
/home/acdev/strikes/1676/sandbox-source-20261011-0111`. This private local authored
copy has 16,945 files and excludes media/telemetry. Use the same frozen path for
dry-run, apply and replay; the live F export is still being updated.
Apply requires explicit --apply, the exact
staging origin and runtime-injected AC_SANDBOX_IMPORT_COOKIE. The CLI never reads
the server secrets directory or prints a credential/request body. It verifies the
currently selected flagged target before writing and exact counts after importing.
Only loopback and this staging target are accepted; production is refused.

## Validation receipt

The complete frozen-copy offline dry-run passed with dataset SHA256
`ae3f28af6b547d5726dd6f183461edb6a999d6d31cefbd58e1ed32a78510c2a8`.
It validated 875,550 master/history records, 177,615 call summaries and 3,360 full
bundles without opening a network session. Forty focused unit cases and four real
PostgreSQL cases pass; fourteen registry/backup-parity cases also pass.
The separate composed bulk report/delivery regression passes. Three
cookie/PostgreSQL cases prove opt-in refusal,
exact report preservation, no run/job/usage write, current-role denial, private
coaching, replay after a fresh client, racing imports, immutable history and atomic
superseding revisions. Metadata comparison against real migrations has no drift.
The added operator test covers read-only preview, idempotent apply/audit and the
environment guard. Unit proof covers schema/identity/media boundaries, filesystem
escape, production refusal, request splitting and source-pin drift.

Sensitive migration, intake authority and backup files require CTO/CEO review.
PR #442 currently holds the shared migration slot and introduces another 0081
successor to main's 0080. The combined linear chain and parity must be checked
after source integration. No final CI/deployed/sandbox-loading claim is made by
this local evidence.

After integrating main bcd4e40, all five sandbox/member-delivery PostgreSQL cases
passed together (73.48s). Dev/live then reported an add/add conflict: Admin's
unpublished 3d6e89b introduces a read-only `synthetic_dataset.py` and same-named
test. C's ingest adapter is renamed `synthetic_import_dataset.py` and its test
`test_synthetic_import_dataset.py`; CLI references follow the new name. The
adapter body and pinned dataset are unchanged, and no Admin file is edited.
