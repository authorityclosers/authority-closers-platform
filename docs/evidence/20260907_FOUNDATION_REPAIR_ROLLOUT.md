# Foundation repair rollout — preparation evidence

Status update: the exact foundation repair is installed and healthy. The
post-deployment and 16:21 UTC logical restore sections below supersede the
preparation-only status. Full foundation and production restore acceptance
remain separate; the new passing proof is specifically the staging database.

## Baseline and retained recovery state

The checked live foundation remains
`foundation-62538c11e679d757648ca691cc26ece5ba64cb39`. Its complete release-file
checksum check passed. All 55 installed manifest targets matched their released
source bytes and expected root ownership/modes immediately before capture.

A fresh root-only recovery archive was created from those exact 55 targets,
the two existing pinned tool binaries, the current foundation toolchain marker,
and the existing `current` symlink: **59 entries**. It does not replace Git as
configuration authority and is not a database or off-host backup.

- Path: `/root/ac-bootstrap-backups/pre-foundation-20260907T153856Z.6xP9p0.tar.gz`
- SHA-256: `d91132fa48cb2ed2c55a25b266d1d02e82e3ae787670200ac43d83fa30135d8e`
- Size: **85,037,354 bytes**; owner `root:root`, mode `0600`.
- Parent: existing non-symlink `/root/ac-bootstrap-backups`, `root:root 0700`.
- GNU tar comparison against the existing host files passed; the entry count
  was exactly 59 and the current foundation link was unchanged after capture.
- The archive was created under a fresh partial filename and renamed only
  after those comparisons. Historical host archives were not overwritten.

The capture command's final, redundant `stat` failed because the PowerShell
stdin transport appended a carriage return to its last argument. Archive
creation, comparison, count, mode check, rename and digest output had already
succeeded. A separate exact-path SSH `stat` then independently verified the
final byte count, ownership and mode above. The first command's nonzero exit is
retained here rather than reported as an entirely successful command.

## Recovery services: do not overstate the diagnosis

Read-only inspection found foundation backup and foundation restore-check
failures caused by repository lock contention. Later logical backup unit
completions succeeded through 15:19:13 UTC; earlier failures do not establish
that every later upload failed. A 15:20 local logical dump passed its sidecar
hash, size and `pg_restore --list` check. Neither result is an actual restore
drill or independently proven off-host copy.

The staging off-site restore-proof timer was disabled, its last recorded run
failed on September 1, and no retained staging proof JSON was found. The repair
must not silently enable that timer or treat the old failure as acceptance.

## Remaining controlled actions

Require the final exact foundation commit's complete Linux CI, review the full
delta from the baseline, revalidate this archive and current static state at
installation time, and use the immutable foundation installer from the verified
Git archive. Preserve existing timer states and allow active jobs to finish
before replacing their helpers. Do not invoke bootstrap runtime, which restarts
Docker, or hand-edit/reload the live Caddyfile.

After installation, verify exact files/link/mounts, edge and collector health,
unchanged application routes, and synthetic credential redaction in both access
and runtime-error logs. Actual serialized off-host backup and restore proofs
remain required. Signed-film activation and production acceptance are not
established by this preparation artifact.

## Controlled deployment and live proof — September 7, 16:04–16:10 UTC

The final reviewed/merged foundation commit is
`a6d8472a31bff67c9cfcfce886a80e606a34f88a`. Exact main Application validation
`34140250287` and Control-plane validation `34140250312` both passed. The complete
delta from the retained `62538c11` baseline was ten foundation files: the Caddy
two-sink redaction, five backup helpers, restore-proof writable-leaf unit change,
leaf preparation helper/bootstrap invocation and its runbook. No OS/image pins,
Docker daemon settings, ingress routing or account permissions changed.

The controller created a path-safe, exact Git-commit tar archive of only
`infra/vps-foundation`: **450,560 bytes**, SHA-256
`746ff8293cbb16f829ab176fcd8c1ca5ef353775c0e2ed63d66504db5dac0cac`.
The matching trusted verifier checked it locally and again on the VPS before
extraction. Remote execution staging is the new root-owned `0700` directory
`/var/tmp/ac-foundation-a6d8472.qo4IUn`; source is not the dirty worktree.

Immediately before installation, all 55 old managed targets again matched
source bytes, owner and mode; the complete old release manifest passed. The
retained recovery archive above passed its SHA-256 and actual `tar --compare`
against current host files. The root-owned `0700` drill-input leaf was verified.

The three already-active backup timers were temporarily stopped. The existing
logical backup job was allowed to finish, not killed or restarted. With all
relevant jobs terminal, the existing private Restic lock was acquired for the
installer window; no lock file or remote Restic lock was removed. The same exact
archive's `install-foundation-release.sh` ran directly, not `bootstrap runtime`.

- Install started **16:04:38Z** and completed **16:04:58Z**.
- Pinned OS validation, downloaded Infisical/rclone archive and binary checks,
  all 55 installations and foundation Compose health checks passed.
- Edge and collector were recreated with the new immutable bind paths. Docker
  itself and all five application containers were not restarted by this repair.
- `current` now resolves to `foundation-a6d8472a31bff67c9cfcfce886a80e606a34f88a`.
  A second complete release/file/owner/mode verification passed for all 55 files.
- The actual read-only Caddy mount points into that release and its file SHA-256
  is `f4d41bc1d54e932f27a99459314d446c76d576e38217ef6ad428e105b0a07617`.
- Foundation local/public health and staging public health passed. Application
  `current-staging` remains `a5eef0df4b340070ac6e58f9912d73a3bf1d2f18`.
- The maintenance wrapper exited zero, including timer restoration. Daily
  foundation backup, weekly restore check and logical backup returned to
  active/enabled; staging and production off-site proof timers stayed
  inactive/disabled. No timer enablement was inferred from installation.

The live edge synthetic probe made one `/healthz` request (200) and one request
through the existing, unconfigured production API host route (expected 502).
It sent only seven clearly invalid synthetic query values and no cookies. This
exercised a genuine upstream error without interrupting staging or creating a
production service. Logs were parsed in VPS memory and only safe counts emitted.

At **16:09:48Z**, one `http.log.access.log0` event and one
`http.log.error.log0` event each had all seven values replaced with `REDACTED`;
the complete 2,512-byte captured interval contained **zero** original marker
occurrences. The first probe at 16:09:06Z failed its test because it looked for
the unsuffixed error-logger name. Safe field-only inspection found the real
`.log0` namespace and already-redacted error event; the corrected new probe
passed. The failed assertion is retained, not described as a passing run.

This closes deployed edge-log redaction, not signed-film playback or production
readiness. Fresh canonical logical backup/off-site restore proof, publication
authority, film activation and authenticated learner streaming remain separate
acceptance results. The earlier release and durable host archive are retained.

## Actual staging logical backup and off-site restore — 16:16–16:21 UTC

The canonical `ac-postgres-backup.service` and
`ac-restic-postgres-restore-proof@staging.service` each ran once and completed
with `Result=success`, `ExecMainStatus=0`. Their execution PIDs were 872581 and
875440. The logical backup timer was temporarily paused for serialized testing
and restored active/enabled; no disabled proof timer was enabled. A subsequent
timer-driven backup is not another test run or a failed cleanup.

Retained source evidence directory:
`/srv/authority-closers/recovery-evidence/postgres-logical/staging-20260907T162119Z-43f1acfb1dbb`.
Both `off-site-restore-proof.json` and `restore-drill-43c7f6ac03ba.json` say
`passed`. The root independently re-read these files and terminal service state.

- Application, backup and restored workspace: exact release
  `a5eef0df4b340070ac6e58f9912d73a3bf1d2f18`.
- Backup captured 16:16:34.557127Z; remote snapshot created 16:16:39.994060Z.
- Drill started 16:21:27.897828Z, completed 16:21:35.276501Z.
- Observed backup age **293.341 seconds**, below the **900-second** target.
- Measured restore boundary **6.939 seconds**, below **3,600 seconds**. Boundary:
  `restore-verified-marker-held-worker-provider-call-blocked`.
- Objective and operation gates passed. All 39 representative canonical tables
  were checked; migration head was `20260904_0018` at this release.
- External connections were empty. Held worker had zero provider calls,
  `run_once_rejected=true`, `worker_ready=false`.
- Exact run-label container/network/volume cleanup completed; independent
  inspection found no remaining resources bearing label value `43c7f6ac03ba`.

This was a small staging dataset, not a production-scale recovery/performance
guarantee. Earlier September 1 failures remain historical failures. This proof
does not certify full foundation restoration, media playback or production.
