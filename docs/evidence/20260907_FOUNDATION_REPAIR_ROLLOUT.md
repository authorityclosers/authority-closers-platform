# Foundation repair rollout — preparation evidence

Status: preparation only; no foundation installation, timer change, container
replacement, logging activation or restore acceptance is claimed.

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
