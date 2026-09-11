# Reconciled Alpha release candidate — 2026-09-11

Status: locally assembled, independently checked at integration seams, and
validated within the recorded Windows/local test limits. No publication, deployment,
production activation or executed migration rehearsal is claimed.

## Immutable inputs

- Main baseline: `1c20a80280e83c6d20e835dd96538f2f8c1f0e0b`.
- UI checkpoint: `edb6ea903a4374f3286f333affea12bf795ced40`, including
  next-action commit `7abd38e5584ae2bb12de48feb2a0ba0d3bb21a44`.
- Independently reviewed scanner: `1812a53e21df4b79aed9e8e9a820b404a0c9b5a2`.
- Independently reviewed local backup repair:
  `f3f3a68aa2583f09782a361a56fede151d11bad0`.
- Seven retained rehearsal files from the explicit September 11 transfer
  manifest, checked against their original SHA-256 and byte counts.

The only product writer remains the preserved d2de tree. Its post-checkpoint
course-intent work is excluded. The release worktree is 9191 on
`codex/v02-reconciled-release-20260911`. Scanner and backup review branches are
preserved separately, and the saved main checkout was not changed.

## Reconciliation and preservation

The complete Git-object inventory compares final bytes, with rename detection
disabled, against the exact main baseline: 305 differences (180 additions,
123 modifications, two deletions). Its SHA-256 is
`0b53829dc3aff7d2e9038ec8b7bd1595b02f10defff082f38c1e7878fded1eb8`.
The inventory records 46 checkpoint paths, including six already identical to
main. It is source evidence, not release approval.

Three-tree classification against common ancestor
`ec0009ec0ea0333d7cfa266d2c353d07ddaf1268` found 206 candidate-only changes,
five main-only changes and 94 paths changed on both histories. A local merge
preview confirmed the squash ancestry cannot be merged blindly.

The explicit materialization copied 287 candidate files with Git blob identity,
SHA-256 and byte-count checks, plus five exact scanner files. It retained all
seven frozen rehearsal files and the repaired backup controller. Only the
candidate's 17 parity declarations were added to that controller; the newer
capture, quota, retention and sanitized-failure behavior remains intact.

Twelve main paths were preserved byte-for-byte. These retain the approved
staging-only demonstration policy, installer and test ShellCheck annotations,
public-film policy/legacy-off tests, logged-out and replayed-cookie rejection
proof, whole-download deadline and its regression, and historical evidence.
Two alternate candidate evidence records are preserved separately as
`20260911_FROZEN_UI_COMMUNITY_EVIDENCE.md` and
`20260911_FROZEN_UI_COACH_EVIDENCE.md`; they do not overwrite main's records.

The source owner's single original-file formatting correction is recoverable
from `local-api-upstream.test.original-20260911.ts`, SHA-256
`981819c7f4f8c0ae02b5663a3541ab9e24d11f07445cb04968c75ce09dbd95e0`.
It was independently checked as parameter-list whitespace/trailing-comma only.

## Independent review

Integration-seam review verified the exact 17-line backup delta, all seven
rehearsal files, all five scanner files, candidate parity helpers/tests and
migrations, and all twelve preserved main paths. No actionable seam finding
remained. This is not a blanket review of every product behavior.

The public-film review confirmed the existing 12-second pack remains compatible
with the integrated media/HTTP code. Its approved digest remains
`dc8f635df33432aee83c461535823881286ded1577a8f8a72dc5b10f0ad86b42`.
The separate full-film manifest and local Studio composition do not activate
full-film delivery, staging/production uploads or providers.

Migration review confirmed v7/0027 contains 55 parity tables; v8/0028 contains
57, adding one global identity per distinct legacy person and preferences per
legacy profile; v9/0029 contains 58, adding initially empty read receipts.
Both new migrations refuse downgrade. Collision checks precede backfill.

## Executed validation

- Frozen frontend checkpoint: 2,204 tests across Learner/Admin/Coach, all three
  TypeScript/lint checks and repository Prettier passed. Source-owner inventory
  audit found no omitted original frontend runtime/test/config files outside
  the checkpoint, apart from generated Next declarations. Exact final CI remains
  required independently of this working-tree evidence.
- Integrated Python Ruff check passed; all 411 package/test files passed format
  verification. Scoped infrastructure lint and diff whitespace checks passed.
- Focused integration run: 613 passed, 20 skipped and four shell-dispatch
  environment failures. All four passed unchanged through Git Bash's login
  environment. Thus 617 focused cases have passing evidence; the twenty
  POSIX/Docker/opt-in PostgreSQL gates remain unexecuted locally.
- Initial restore collection required the exact worktree's per-process Git
  safe-directory configuration. No global Git configuration or test assertion
  was weakened. A PATH-prefix attempt did not repair Git Bash; its login
  environment supplied the required shell tools.
- Broader unit/database/infra run: 4,032 passed, 94 skipped, eight failed and two
  warnings. Seven failures used the Windows Store `python3` alias rather than
  the locked Python runtime; one installer fixture could not create its sandbox
  temporary parent. The two affected test files match main unchanged. All eight
  passed in a targeted rerun using a local runner-only `python3` shim to the
  existing virtual environment and normal user filesystem permissions. Thus
  4,040 broader cases have passing evidence across runs, not a single green
  full-suite run. The 94 platform/disposable-database skips remain for CI or
  the corresponding controlled runtime checks. No product source or assertions
  were changed to address the runner environment.
- Full Python type checking passed with no issues in 192 source files.
- The explicit release path inventory contains 307 changes against the main
  baseline: 294 materialized candidate/scanner/evidence files, seven frozen
  rehearsal files, five backup-repair files, and this integration evidence file.
  Only these paths are eligible for the local checkpoint. Its commit identity
  is recorded in the external recovery packet to avoid a self-referential hash.

## Remaining release gates

Final local checkpoint, exact CI, immutable image/archive binding,
compatible v8/v9 foundation installation, paired exact-release backup, scanner
Docker and functional readiness, isolated prior-head migration rehearsal and
cleanup, authenticated target-release staging smoke/screenshots and Drive
filing remain required. The rehearsal's generated owner with `--no-owner
--no-acl` does not prove deployed runtime/backup role permissions; canonical
CI migration/privilege and backup-role dump/list gates remain separate.

Source API image identity must match the selected paired backup's release and
0027 head. Candidate API identity must match the final reconciled commit and
include `prove-held` plus migrations through 0029. Do not package the earlier
UI checkpoint directly or relabel an arbitrary 0027 image as the source.
Do not restart old 0027 writers after 0029 writes become visible.

Scanner PR53 merge and publication of the separate backup repair are awaiting
explicit approval after automatic approval review rejections. This local
integration does not bypass either rejected action. Offsite quota, governed
production tenant/owner/consent/configuration and later product capabilities
remain separate gates in the broader active release program.

Reproducible object inventory, three-tree classification, materialization
receipt and local update/prerequisite plans are in
`D:/Projects/authority-closers-release-transfer/2026-09-11-recovery`.
