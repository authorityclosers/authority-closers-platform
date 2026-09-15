# Sales Xray release validation repair

This record supersedes no failed receipt. Application run `34763521687`, source
`ef6f9514f682048ab210a01400ac434dd00346ca`, failed with 22 failures, one error,
5,077 passes and 759 skips in the full Python suite. Its immutable release image
job was skipped. That source was not promoted by this lane.

The repair retains the existing application, authorization and installer gates:

- Rollback and film-dispatch harnesses now include the actual hosted capability
  loader and drain helpers. They check core/web stop ordering, fencing, restore,
  edge restoration and runtime grant before restarting the previous release.
- Hosted runtime and browser fixtures supply their canonical operations tenant.
- Free-course fixtures refresh their current-session clock for each proof and
  bind media issue/verification to that clock. Expired fixtures remain expired.
- Activation tests use a disposable root-owned `/run` tree and immutable external
  files on Linux. CI runs the module with root privileges in its ephemeral runner
  and saves its JUnit receipt. The ordinary unprivileged suite defers these
  fixtures to that required job; a required invocation without root fails.
- Negative activation cases first establish successful admission, then test
  foreign ownership, owner-writable files, extra hard links and writable parents.
  The production validator is unchanged.

Local receipts outside Git:

| Receipt | Result |
| --- | --- |
| `D:/AC-authority-closers-release-audit/v02-release-harness-repair.xml` | 146 passed, 7 skipped; Windows/Bash release and film regression checks |
| `D:/AC-authority-closers-release-audit/v02-hosted-lifecycle-windows-04.xml` | 17 passed, 16 POSIX cases skipped; not Linux ownership evidence |
| `D:/AC-authority-closers-release-audit/runtime-fixture-settings.xml` | 167 settings tests passed |

Full Linux CI, immutable images, hosted activation, authenticated staging
acceptance, production canary and production acceptance still require actual
receipts. Neither a local pass nor a proposed approval bundle proves deployment
or authorizes provider execution. At the 2026-09-13T15:17Z VPS read, the existing
core staging/production containers were healthy on `69db2257…`; Sales Xray native
supervisor units and external activation descriptors were absent. Provider token
file metadata was checked without opening the files. No provider call or paid
operation was performed in this repair.
