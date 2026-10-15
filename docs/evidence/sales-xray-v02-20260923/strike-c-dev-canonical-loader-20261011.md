# AUT-1676 dev canonical sandbox loader — incomplete acceptance

The owner-requested dev loader uses ordinary conversation models for the exact
AC Sandbox tenant and preserves the source-authored report, coaching, transcript
and answer key. It adds 60 fictional members without login credentials, 3,360
completed local calls, zero-second released usage records and an attributable
audit receipt in one transaction. Optional history uses the existing synthetic
summary adapter and the normal company Insights refresh. It refuses staging,
production, alternate connection options and changed imported history.

## Validation collected

- All 3,360 source reports pass the canonical report validator offline:
  26,040 cited skill observations and 840 explicit evidence gaps; 60 reps.
  Source bundle hash-list digest:
  `26adb0da3ca993a04167ffbfc967348687c025b1d594f8dea9c251834474adec`.
- Focused run: 13 unit cases pass; the PostgreSQL case fails when constructing
  its new historical-summary fixture, before its history/replay/rollback section.
  The fixture is missing `schema_version`, exact `call_id` and six report pillars
  required by `SyntheticRecordInput`. The loader does not bypass that contract.
- Earlier assertions in that same database case pass: concurrent load/replay
  yields exactly one canonical call; normal library/report/progress/coaching
  reads succeed, accounting totals zero, audit verifies, no login credentials
  are created, run alarms are empty and normal Insights pending is zero.
- Changed-file Ruff, format and whitespace checks pass.

Command: `uv run pytest tests/unit/conversation_intelligence/test_dev_sandbox_loader.py tests/database/test_dev_sandbox_loader_postgresql.py -q -x --tb=short`.

## Remaining acceptance

The fresh task gate now refuses source work because Dependabot PR #464 is
classified as an exclusive task. The unfinished fixture correction and final
green PostgreSQL proof remain pending; this source is not ready to merge.

Root moved served live dev to dedicated `172.27.0.12:5432/ac_platform` on
11 Oct; the older loopback `ac_dev_live` is unused. The loader pins the current
dedicated target. Its runtime credentials are not available to this session.
Exact credential-injected root preview/apply commands are in
`/home/acdev/strikes/1676/NOTES.md`; no secret was read or printed.

No hosted data was loaded. Read-only dev health is ready at main `0b50b2c` and
sandbox import is present (401 signed out). Normal JSON transcript sources are
created; the seven media files remain preserved in the input publication and
are not claimed as playable recording objects. Actual dev calls/report/coaching/
people/chart reads remain required after the operator load.
