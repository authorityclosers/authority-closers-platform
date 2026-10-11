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

The full bundle preserves metadata, authored transcript/timing, six report pillars,
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
batches roll back completely. Seven canonical MP3 attachments now pass the exact
F media handoff. Their SHA256, complete local decode, duration, timing, speakers and
text are independently checked. Forty-nine recordings attached to older wording
are excluded. `silence_aligned` remains approximate; that provenance is preserved.

Media manifests bind to the complete authored-call hash. The byte route uses the
existing private recording/scratch store, upload cap, source preflight, storage
fence and current session/profile checks. Native validation precedes delivery;
raw client claims do not enable playback. A slow upload spools before the global
storage fence. Immutable audio records retain the measured receipt; a process
restart after file publication reuses only verified identical bytes. Read
projections disable playable flags until delivery, preserving original stored
history. No acquisition, provider task, AI run or customer minute is created.

## API for integration

Prefix: `/v1/conversation/acquisition/imports/sandbox`.

- `POST /calls`: `synthetic-call-bundle/1`, with Idempotency-Key.
- `POST /records`: `synthetic-record-batch/1`, with Idempotency-Key.
- `GET` prefix: selected sandbox ID, counts and authored date range by kind.
- `GET /records/{kind}`: up to 100 current revisions and an optional next_cursor.
- `GET /records/{kind}/after/{cursor}`: exact key pagination.
- `GET /calls/{call_id}`: metadata, transcript and authored report.
- `GET /calls/{call_id}/coaching`: private authored coaching.
- `POST /calls/{call_id}/audio`: bounded `synthetic-call-audio/1` manifest.
- `PUT /calls/{call_id}/source`: exact-size `audio/mpeg` bytes, Idempotency-Key.
- `GET /calls/{call_id}/source`: current-session private playback with one byte range.

Call reads add audio.state (`not_provided`, `awaiting_upload`, `ready`), playable
and the private source URL only when retained. Every body/state remains synthetic.

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

Dry-run the corpus through `ac-heavy uv run python -m
ac_platform.conversation_intelligence.synthetic_import_cli --dataset
/home/acdev/strikes/1676/sandbox-source-20261011-0215`. This private read-only copy
has 16,960 files, including seven verified MP3s and timing/verification receipts;
telemetry and legacy audio are excluded. Use the same frozen path for
dry-run, apply and replay; the live F export is still being updated.
Apply requires explicit --apply, the exact
staging origin and runtime-injected AC_SANDBOX_IMPORT_COOKIE. The CLI never reads
the server secrets directory or prints a credential/request body. It verifies the
currently selected flagged target before writing and exact counts after importing.
Only loopback and this staging target are accepted; production is refused.

## Validation receipt

The complete frozen-copy offline dry-run passed with dataset SHA256
`24373620f67b8656de9bd1dcbde59b35e5c2ee498367fa5fa5a757692af8c058`.
It validated 875,550 master/history records, 177,615 call summaries, 3,360 complete
bundles and seven audio manifests/files without opening an HTTP session.

All five actual cookie/PostgreSQL sandbox cases pass together (21.14s): explicit
opt-in, private report/coaching preservation, no run/job/usage creation, atomic
conflicts, superseding revisions, racing imports, role revocation, migration
metadata parity and the audited exact-target opt-in script. The new media case
uses a real locally generated fictional tone, normal native preflight, atomic
publication/restart/replay, private byte-range delivery and current-role denial.
Stored authored content remains identical when read projections disable playback.
Its local fixture reuses the existing test-only ac-heavy guardian bridge; the
live ancestor is still verified and no runtime environment gate is weakened.

Fifty-one focused schema/adapter/media unit cases pass (1.81s); 25 adapter/security
boundary cases pass (13.19s, overlap with the preceding adapter cases). Eight-source
mypy and changed-file Ruff pass. The earlier 14 registry/parity and composed normal
bulk delivered-report proofs remain valid: the audio addition adds no table or
ordinary charging path. Previous text-only source pins remain historical receipts
in NOTES.md; the operator must use the newer frozen source above.

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

Final prior-head CI at 7ed697d passed every application check except one historical
prospect assertion still expecting 0080 rather than 0082. Strike B already fixes
that assertion with _migration_head() at #439 / 7995d9c; C does not edit its owned
file. Reviewed main integration is required for final combined-tree CI. The
shared migration-slot hold remains separate. No hosted sandbox data was loaded.

## Regional corpus and operator read-back continuation

Strike F published `regional-journeys/1` after the independent/language revisions.
The new private, read-only frozen input is
`/home/acdev/strikes/1676/sandbox-source-20261011-0344`, SHA256
`623324255bfe70af237bc62d541f50d0d988a019625054fb3f2518bb4ff3e3d2`.
All 16,807 published bundle hashes and 16,968 copied files were checked against
the live source at freeze completion. Its current/regional/independent/evaluation
verification receipts are pinned and report PASS with no errors. Native fluency
remains unverified. Earlier immutable copies and operator guides remain historical.

Complete offline validation passes through the unchanged dataset adapter and
validation function: 875,550 master/history records, 177,615 summaries, 3,360
full report/coaching bundles, seven audio manifests and seven full decoded media
files. Every actual request batch and exact text/speaker/timing binding validates;
no HTTP session or hosted write is used. Source receipts are in Strike C's
`sandbox-source-0344-copy-receipt.json`, `sandbox-source-0344-validation.json`,
`sandbox-source-0344-assurance-receipt.json` and
`logs/sandbox-regional-frozen-proof.log`. The named operator guide now uses 0344.

An operator regression reproduced a false verification on the previous CLI: the
final response could contain a different tenant's otherwise equal counts. Initial
and final progress reads now require the same exact tenant and explicit
`synthetic=true`, `sandbox=true` markers. Malformed objects, boolean counts and
repeated record kinds fail cleanly. Initial refusal sends no write; final refusal
never returns an applied receipt. Intermediate writes still follow the ordinary
selected organisation, so the sole operator must keep that session selected to
AC Sandbox throughout the run. This change does not claim a target lock or
introduce another trust path.

Shared dev `/review-fixture/bulk-import` returned 404 on this continuation. No
private Next server or additional production build was started. The previous
standalone fixture screenshots remain historical; populated shared-dev proof
still needs Strike A's bulk-island mount. Migration serialization, sensitive
review, Root's served-organisation update and Claude's staged import/read-back
remain required. No staged data loading or complete delivery is claimed.

Focused final verification: all 24 adapter/operator tests pass (5.88s), including
12 initial/final target and malformed-receipt cases. Changed-file Ruff/format,
one-source mypy and diff whitespace pass. The pre-fix wrong-tenant regression
failed as expected (5.65s). Logs are `sandbox-target-readback-before.log` and
`sandbox-target-readback-verified.log` in the strike folder. No database/runtime,
ledger, HTTP route, UI, dependency or foreign strike file is changed by this
follow-up; final-head CI remains required after publication.

## Buyer-boundary publication and exact-target assertion

The immutable operator input is now
`/home/acdev/strikes/1676/sandbox-source-20261011-0424`, SHA256
`fe51b45f8b786aaff8b1750388f66061503cbfee775447f84b59f405c8e06e3f`.
It contains the published `buyer-boundaries/1` revision, with 87 separately
authored calls in 29 journeys and unchanged complete corpus totals. All 16,807
published bundle hashes match the 16,978-file copy. The final delivery receipt
binds its CSV, bundle index and bundle-hash receipt; all nine assurance proof
pins and PASS states were independently matched. Two supplemental check receipts
are retained separately, preserving the frozen dataset. Full offline request,
record, bundle and seven-media hash/decode/text/timing validation exits zero.
Earlier immutable inputs and guides remain intact. Native fluency is unverified.

The importer carries `X-AC-Sandbox-Tenant` on every request. The header asserts
the operator's exact intended target against the authenticated actor and service
workspace. It cannot select an organisation or grant permission. Existing cookie,
origin, current role, profile and immutable sandbox-flag checks remain required.
The assertion is optional for existing readers; when present, malformed or repeated
headers are refused and a changed selection fails before any import write. Audio
checks the target before receiving bytes and again after spooling. This supersedes
the earlier intermediate-write warning in this verified server change.
No new schema, identity grant, billing or provider behavior is introduced.

The original CLI regression fails because it sends no intended-target header.
The new real-cookie/PostgreSQL regression changes the session between two
explicitly flagged, served organisations and checks all four write paths before
any synthetic record is created. All 24 operator unit cases (7.19s) and all six
actual sandbox PostgreSQL cases (33.60s) pass. Changed-file Ruff/format and
three-source mypy pass. Replay, simultaneous imports, private native media and
zero charge/job writes are verified with the bound requests. The original server
returned another flagged tenant from the bound GET; the final server refuses all
four wrong-target write paths and malformed/repeated headers with zero imported
records. Receipts: `logs/sandbox-target-prefx-unit.log`,
`logs/sandbox-target-prefx-postgresql-second.log` and
`logs/sandbox-target-final-checks-second.log` in the strike folder. No staging or
production import, deployment, service change or manual merge is claimed. #437
remains closed under the recorded #446 -> #442 -> #437 serialization order.
