# AUT-1405 scheduled backup due-time evidence

Source: [authorityclosers/paperclip PR #31](https://github.com/authorityclosers/paperclip/pull/31),
head `19e73f87e9f3e1524cbabd891eb3e3610e3276cc`, based on
`63f2d8510375e55c28ef0f70748119f0d440914f` on the supported
`ac/v2026.916.1` branch. The owning task is
[AUT-1405](/AUT/issues/AUT-1405).

The source adds a durable next-due record in the existing backup directory.
File sync, atomic rename and directory sync protect each checkpoint. Startup
recognizes an overdue backup and invokes one catch-up. The first installation
runs immediately. Only successful scheduled backups advance the time, anchored
to their start; manual jobs and failed/skipped attempts do not advance it.
Both the existing shared in-flight guard and the scheduler tick guard remain.
Configuration, retention, compression, existing dump contents and adapter
packages are unchanged.

Verification on 6 October 2026: eleven filesystem-backed scheduler tests pass
with Vitest 4.1.11 and one worker. TypeScript 7.0.2 checks the scheduler and its
tests. Both emitted runtime modules pass `node --check`. The emitted scheduler
also passes a fictional early-restart, overdue-catch-up, repeat-restart,
failure-delay and saved due-time cap proof.
No real database, service or backup invocation was used for these tests.
Full server typecheck, full workspace tests/build and deployed cadence were not
run or claimed.

The four CTO-requested regression cases fail against prior head `a18ab19` and
pass at this head. They verify no retry at +1 or +14 minutes after a failed dump,
one retry at +15 minutes, a shorter interval measured from failure completion,
and persisted due-time caps after an interval reduction or a prior clock error.
Failures retain the saved anchor; the retry delay is in memory only. Valid due
times within one interval remain unchanged across restart.

[Immutable four-file runtime candidate](/api/attachments/185f1e57-db91-4479-a7d0-52ffc34d2b49/content?download=1):
SHA-256 `987a05e18ae4325b43be8d558fce833084334fb2e87df743ff7e6596ce83900b`.
The archive contains the pinned manifest, native compiler settings, fictional
emitted proof and supported managed install/rollback instructions. It replaces
only the entry-point module, the new scheduler module and their source maps.
The base entry-point source blob is identical to deployed server source
`d554c4789ed3930f8a53ac9fdf6503b3187097da`. Every package byte outside that
bounded overlay must be preserved, including the approved adapter overlay.
The archive includes the eleven-test output and the four failing regressions
against the prior head. Downloaded bytes and all four runtime hashes match.
The emitted entry-point JavaScript is byte-identical to the prior candidate.

Limits: one server process owns this schedule. A crash after a successful dump
but before checkpoint commit can cause a safe duplicate catch-up. Invalid state
is preserved and logged for operator repair; the API can still start.

Remaining delivery: CTO review, CEO approval at the exact heads, approved merge,
Root's managed installation and supported quiet-point restart, then two actual
successful scheduled dump starts about four hours apart, preserved nextDueAt
across a quiet restart and HTTP 200. Root must set a bounded monitor from the
actual deployed due time. No monitor or installed fix is claimed yet.
[AUT-1376](/AUT/issues/AUT-1376) requires that real cadence output before closure.
