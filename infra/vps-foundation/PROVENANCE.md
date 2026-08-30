# VPS foundation migration provenance

- Historical local source: `work/authority-closers-infrastructure`
- Historical repository head at snapshot: `22fa9d9` (`Harden R2 client compatibility`)
- Snapshot date: 2026-08-30
- Destination: `authorityclosers/authority-closers-platform`, `infra/vps-foundation`

The snapshot includes the historical working tree's modified and untracked operational files because live SHA-256 checks showed that the active VPS backup, restore, R2 guard, and Infisical wrappers match those files. No Git metadata or secret files were copied. The historical repository remains intact for provenance and rollback investigation.

This snapshot is not evidence that G0 passed. It is the input used to reconcile the live runtime with an immutable, reviewable release.

## 2026-08-30 logical PostgreSQL backup addition

The bounded logical PostgreSQL writer is an additive foundation release change. It uses the already-installed Python 3, Docker Compose, Infisical, Restic, coreutils, `flock`, and PostgreSQL client binaries; no toolchain version or binary checksum was changed. The new scripts, policy fields, and systemd units are included in `config/release/install-manifest.tsv` and will be covered by the installer-generated `RELEASE-FILES.sha256` for the exact foundation Git release. The writer remains disabled until its explicit activation gate passes; this change is not live activation or measured G1 evidence.
