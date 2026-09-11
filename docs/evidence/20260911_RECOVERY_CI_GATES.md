# Required recovery CI prerequisites — 2026-09-11

Status: independently reviewed and locally validated follow-up to reconciled
checkpoint `e39f2bd84393189a7b68b348555eb83d1cd413f9`.
This record does not claim an executed GitHub run, image build, live restore
rehearsal, or staging/production acceptance.

## Findings and changes

Read-only CI coverage review found that the populated 0027→0029 regression
would skip without its dedicated URL. The job-kind isolation and Studio
worker-fence fixtures would instead fail: they require
`127.0.0.1:55432/ac_local_sandbox`, while CI's test media URL selected the
canonical database on port 5432. The fixtures' existing endpoint restrictions
were retained unchanged.

Application CI now provisions a second PostgreSQL service using the same
pinned PostgreSQL 18 image as the canonical service. Only the test media URL
selects its `ac_local_sandbox` owner target. The canonical `ac_platform`
runtime/migrator role split, migration chain, backup-role dump/list and
privilege assertions remain on the original service. Each media/worker suite
still creates and removes its own generated schema.

An explicit required step exercises worker allowlists, Studio recovery fences
and the existing operations-bootstrap regression against the disposable owner
target. A separate empty `ac_migration_rehearsal_ci` database is created on
that same ephemeral service, then the dedicated populated prior-head test runs
with its required flag. This verifies synthetic migration behavior; it does
not replace the exact-backup/two-image restore-drill gate.

Both validation workflows fetch history and require the exact historical
controller object `35c658bd028b4fc3a7c048ab72dae700cd7682d6` before tests, so
the compatibility proof cannot silently skip due to shallow checkout.
The parity module requires root on POSIX. Its Git read now trusts only the
exact checkout via a per-command setting, and control-plane CI explicitly
forwards a required-proof flag through the root/sudo test invocation. Missing
Git or an unreadable object fails this required gate rather than skipping it.
The ordinary non-root application suite does not replace this root proof.
Application CI also requires functioning `ffmpeg` and `ffprobe` binaries
before media regressions. Missing runner tools fail the job instead of
silently omitting codec proofs.

Two Node-resolution tests depend on Windows `USERPROFILE` and a bundled
`node.exe`. Their guards now require Windows as well as PowerShell 7 before
reading that fixture path. They remain executable on Windows; other portable
PowerShell tests retain their prior guards.

Executing the previously skipped populated migration regression exposed a
synthetic fixture ordering defect before either new migration ran: the ORM
attempted to insert an Academy profile before its membership. The fixture
now explicitly flushes tenants/people, then memberships, before inserting
profiles. Its rows, expected derivations, migration scripts and assertions
are unchanged. The original fixture remains recoverable from checkpoint e39.

## Verification

Three structural regression tests parse the workflows and verify the actual
service/URL/credential alignment, preservation of the canonical role target,
mandatory test invocations, database creation ordering, historical object
availability and codec prerequisites. Required steps cannot be conditional or
continue after failure. Two additional negative cases require historical-proof
failure for missing Git or an unreadable object. The first focused run passed
23 CI/Windows-bootstrap tests. The final CI/backup-parity run passed 377 tests,
including the required historical controller and both negative cases. Ruff,
format, workflow Prettier, Bash syntax and whitespace checks passed.

The first managed local PostgreSQL run passed five worker/fence/bootstrap
tests and failed the migration fixture as described above. It completed
normally; the generated migration database was removed and the shared
generated-schema inventory was unchanged. The source-bound, sanitized run
receipt is `recovery-postgres-bc05076c3d374286936c1bc56ba53ef7.json` in the
external recovery packet.

After independent review of the fixture-only flush change, the targeted
populated 0027→0029 regression passed. Its generated database was removed and
the shared generated-schema inventory was unchanged. Receipt
`recovery-postgres-1a9b1cc9473c40289fe8c0c9b1187d4e.json` binds checkpoint e39,
the exact reviewed fixture overlay and source hashes. Together the runs prove
five worker/fence/bootstrap cases plus the corrected migration case; they are
not represented as one uninterrupted green run.

The CI wiring, root/sudo historical gate, local proof-runner boundaries and
fixture-only correction received independent read-only review with no remaining
actionable findings. Final commit identity is recorded in the recovery packet.

## Remaining gates

Run both workflows at the final approved commit and inspect actual skip
reasons; the earlier 94 local skips are not a claim that CI covers each one.
Windows-specific proofs, Linux privileged/filesystem proofs, runtime role
checks and disposable database regressions are distinct evidence categories.

Application image packaging remains an explicit workflow dispatch after
validation. The final API image must attest the candidate release and 0029;
the selected paired backup and prior API image must attest the same source
release and 0027. Compatible foundation installation, fresh paired backup,
dry-run and executed isolated rehearsal, cleanup/RPO/RTO, scanner readiness,
authenticated target-release staging smoke/screenshots and governed production
remain required. No runtime service, provider, quota or business contract was
changed by this CI follow-up.
