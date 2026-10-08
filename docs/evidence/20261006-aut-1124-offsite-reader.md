# AUT-1124: off-site reader address-family repair

Source baseline: `386f28ba6f046fd2dda1727ca6736f9260f79709`.
Branch: `task/platform/1124-offsite-snapshot`.
Scope recorded before editing in the task's `repair-scope` document.

Root's [verified comparison](/AUT/issues/AUT-1349#comment-7afdc8fa-1b0c-4d05-90b1-da838f4d92f3)
held credentials, repository and executable constant: the wrapped Restic config
read failed with IPv6 socket creation allowed and succeeded when denied. The
scheduled backup already applies `RestrictAddressFamilies=AF_INET AF_UNIX` and
succeeded. An environment marker alone does not apply this policy. This evidence
does not establish a provider permission or secret defect.

The shared `ac-infisical-run-backup` wrapper now checks IPv6 socket creation
before loading credentials. An unrestricted caller enters a transient unit with
the existing address-family policy and `NoNewPrivileges=true`. A restricted
caller continues in place, preserving the inherited repository-lock descriptor
and projected-byte environment. Unexpected probe failures stop safely; transient
launch failures have no fallback. The child arguments and nonzero status remain
preserved. No proof algorithm, unit, timer, provider or release gate changed.

Validation on the lane checkout, 6 Oct 2026:

- Six fictional wrapper regression cases passed. They exercise the socket probe
  branches, ignore an unproven environment marker, preserve spaced arguments and
  inherited lock FDs, and verify child/probe/launch failures without secret output.
- The exact inline probe returned 10 in an ordinary local child and 0 in a local
  child whose kernel seccomp filter denied IPv6 sockets with `EAFNOSUPPORT`.
  Both emitted no output. The filter affected only that disposable child.
- Repository Python formatting and lint passed; mypy passed for 426 source files.
- Bash syntax, pinned ShellCheck 0.11.0 and foundation security invariants passed.
- Backup/restore/orchestration baseline: 114 passed, 19 skipped, 12 subtests
  passed, one existing failure. The immediate `/proc` cleanup assertion observes
  `R` instead of `Z`, matching the pre-change result recorded in
  [AUT-1348](/AUT/issues/AUT-1348). Its implementation and
  test were not changed here.
- Local control-plane validation passed shell checks, image pinning, R2 usage
  evaluator tests and all 107 PostgreSQL backup tests. It stopped at the root
  restore-proof tests because the lane cannot use sudo. CI's root control-plane
  checks remain required; no local green full-gate claim is made.
- Infisical bootstrap serialization assertions and immutable foundation installer
  tests passed. The installer test verified rollback of a failed host transaction
  using fictional sandbox state.

Production observations below belong to Root's diagnosis, not to this patch:
snapshots `2026-10-06T00:30:58.861899Z` and `2026-10-06T00:26:00.011789Z` were
readable under the established restriction at `00:33:40.190859Z`; newest age was
161.329 seconds. This historical read does not satisfy installed-repair acceptance.

After green CI, CTO review and CEO approval of the exact PR head, the watchdog
merges. Root must deliver the reviewed backup-scoped foundation through the
existing checksum/commit-bound installer, then verify installed-wrapper equality
and a default wrapped production snapshot read with no synthetic policy or
`AC_IPV4_ONLY` override. Capture stdout/stderr in memory and emit only the two
validated UTC time values, newest age <=600 seconds, and fixed result labels.

The scheduled proof/service paths already apply the restriction. This patch does
not prove `restore_check_ok` or authorize a proof retry/promotion. The independent
successful installed-reader output enables the separately controlled retry on
[AUT-749](/AUT/issues/AUT-749). No production action was
performed in this implementation run.
