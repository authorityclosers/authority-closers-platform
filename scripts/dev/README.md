# Sales Xray sandbox loader

`load-sales-xray-sandbox.py` loads the owner's fictional dataset into normal
conversation records in the exact active AC Sandbox organisation. It requires
the current approving owner's UUID and a recorded approval reference.

The current live dev database is `172.27.0.12:5432/ac_platform` in the dedicated
`acdev-live-postgres` container. Root moved it there on 11 Oct 2026; the earlier
loopback database named `ac_dev_live` is no longer served. The script requires
`AC_ENVIRONMENT=development` and refuses any other database, host, port or URL
query options. Credentials are injected at runtime through the existing dev
environment; never pass them as arguments or copy them into a receipt.

Run from the shared workbench
`/home/acdev/src/dev-live/authority-closers-platform`, with that environment
already injected by the named coordinator/root operator:

```sh
python scripts/dev/load-sales-xray-sandbox.py \
  --dataset /home/acdev/strikes/1676/sandbox-source-20261011-0537 \
  --approver-person-id "$AC_SANDBOX_APPROVER_PERSON_ID" \
  --approval-reference "Owner AUT-1701 DEV-FIRST sandbox load 2026-10-11"
```

The default is dry-run. After inspecting its JSON receipt, repeat with `--apply`.
It validates all 3,360 bundles and 60 representatives, then writes members,
normal owned calls and completed reports in one transaction with an audit event.
Every source and label says synthetic. The exact authored report, coaching,
transcript and answer key remain preserved in sandbox records; the normal report
adapter copies only authored findings and their quoted transcript evidence.

Report finding, moment and highlight titles keep complete words within the
48-character contract; an ellipsis marks shortened titles. The full authored
finding remains alongside its title. Strongest Part joins the authored action
and reason as complete sentences, preserving existing terminal punctuation.

The optional `report-pillars/1` presentation carries the authored summary,
highlights, call stages, supported moments and deal guidance alongside the
unchanged legacy report and coaching findings. Every copied citation uses its
exact published transcript line and timing. Closing annotations bind the
authored outcome to the end of the call; Won/Lost remain absent from that
presentation. A dated next event needs an explicitly agreed source event and
an exact spoken date/time with the same India-time offset. Uncited deal
sentences and incomplete missed-chance explanations are omitted. A failed
optional validation falls back to the existing report without blocking import;
the dry-run receipt counts `reports_with_pillars` and `reports_without_pillars`.
Previously loaded report payloads remain immutable: a replay with a different
report hash refuses the change rather than updating it in place.

Synthetic usage is released immediately and has a zero-second no-work settlement.
Completed local jobs cannot enter the provider queue. Member identities have no
password, provider identity or verified-email assertion. Replays skip identical
calls and refuse changes to preserved content or existing membership state.

Once the full calls are loaded, repeat dry-run and apply with `--include-history`
to preserve the 177,615 dated call summaries for history readers. These summaries
do not acquire invented transcripts or reports. The loader calls the normal
company Insights refresh adapter so charts can read them immediately. Keep the identifier/count-only
JSON receipts in the strike notes; full source files stay outside Git.

Verify with a normal dev owner session: select AC Sandbox, open Calls and a
populated report, then organisation members and team Coaching. The normal API
library must show `report_ready` calls, `done` analysis and their representative owners.
Hosted acceptance is complete only after these reads succeed on dev.

The focused PostgreSQL acceptance test exercises normal library/report/progress
reads, two concurrent imports, exact history replay, changed-content refusal,
atomic rollback, the audit chain and zero-charge accounting. It also reads the
preserved authored Team, representative and call Coaching, checks the exact
mission and transcript quote, refuses another viewer's private coaching and
keeps text-only moments nonplayable. Calls → Report → Coaching uses the same
real submission and member IDs written by the loader, including mission and
moment links; legacy Team links remain readable. The actual signed-in Coaching
HTTP route must also match the loaded report's recording ID, source hash,
transcript revision and report revision. Every diagnostic and own-call lesson
quote resolves to a loaded transcript segment within its original time span.
Anonymous requests and requests from another owner in the same organisation
remain excluded from the importer's private authored Coaching. Run only these loader checks
with the existing test database injection:

```sh
ac-heavy uv run pytest \
  tests/unit/conversation_intelligence/test_dev_sandbox_loader.py \
  tests/database/test_dev_sandbox_loader_postgresql.py -q -x --tb=short
```

The 3,360 full calls have authored transcripts and reports. The 177,615 historical
summaries remain summaries and appear in Insights; they are not completed report
records. The seven verified audio examples use the separate existing media import
path. Loading authored text alone does not make playback available.

## Owner's Drive recordings on dev

`import-sales-xray-drive.py` runs the existing ordinary recording importer with
the exact live-dev Host and Origin. It refuses other destinations, redirects and
requests outside acquisition routes. The existing session, current member checks,
recording rights, plan acceptance, source replay and progress handling still apply.
Inject `AC_RECORDING_IMPORT_COOKIE` from a current **dev** AC organisation session;
never put it in an argument or receipt. Confirm Swamini, Ankita and the owner's
member IDs using `--preview` before applying.

The original 89-file manifest stays at
`/home/acdev/imports/drive-calls-20261011/manifest.json`. Four oversized WAVs have
complete lossless FLAC copies in `drive-calls-20261011-compressed`; their original
and derived hashes and decoded-PCM equality are in `PREPARATION-RECEIPT.json`.
The complete 3,628.14-second recording remains over the native one-hour limit.
The private `dev-ready-88-manifest.json` in that folder includes the other 88
complete recordings so the long call can remain held while they advance.
Per-call native checks still verify actual duration at upload.

Run offline first, then the named operator previews the exact dev organisation:

```sh
ac-heavy uv run python scripts/dev/import-sales-xray-drive.py \
  --manifest /home/acdev/imports/drive-calls-20261011-compressed/dev-ready-88-manifest.json

uv run python scripts/dev/import-sales-xray-drive.py \
  --manifest /home/acdev/imports/drive-calls-20261011-compressed/dev-ready-88-manifest.json \
  --base-url http://127.0.0.1:8101 \
  --tenant-id "$AC_RECORDING_IMPORT_TENANT_ID" --preview
```

Save confirmed current dev assignments separately as `member-assignments-dev.json`
in the original import folder. Repeat the offline command with `--members-file`
pointing there. Then use the same manifest/assignments with `--base-url`,
`--tenant-id`, `--apply --confirm-recording-rights --accept-analysis-plans` and a
finite `--max-wait-seconds` window. Repeat the identical command to resume.
`--read-back <batch UUID>` reads its normal status. Failed/held/waiting calls
remain incomplete; keep their IDs and the untouched full long recording for the
owning pipeline work. Do not call a partial import 89 completed reports.
