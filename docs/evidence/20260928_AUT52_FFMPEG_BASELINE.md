# AUT-52 OS baseline FFmpeg package evidence

Date: 2026-09-28

## Inputs

- Existing baseline: `ubuntu-noble-amd64-2026-08-30-v1`.
- Existing resolved list SHA-256: `1f43279b601f915f6fefe54a673c920dc11473db267068eb25168b09a15ae96c`.
- Task receipt: `/tmp/pkgs-added.txt` (163 unique package names), SHA-256 `cb8626e6acc37a294cd670732a1cd74f34c3601240e9b5335e85600ca4960d4c`.
- Resolution environment: Ubuntu 24.04.4 LTS (`noble`) lane runner, using its configured Ubuntu package index.

## Resolution

Read-only command: `apt-get --simulate --no-install-recommends install ffmpeg`.

The simulation resolved `163` package/version pairs (`0 upgraded, 163 newly installed, 0 to remove and 116 not upgraded`). After normalizing the `:amd64` suffix, its package-name set matched all 163 entries in the receipt exactly, with no additions or omissions. The selected `ffmpeg` version is `7:6.1.1-3ubuntu5`. The committed delta fixture preserves the receipt's package names and pins each resolved version.

- Frozen baseline fixture: `tests/infra/fixtures/os-baseline/ubuntu-noble-amd64-2026-08-30-v1.tsv` (SHA-256 `1f43279b601f915f6fefe54a673c920dc11473db267068eb25168b09a15ae96c`).
- FFmpeg delta fixture: `tests/infra/fixtures/os-baseline/ubuntu-noble-amd64-2026-09-28-v1-ffmpeg.tsv` (SHA-256 `459a7dfcb2c26063df55b9a37dd351c3484cf03c30cc51d8a2bbdd65dba26f2a`).
- New resolved list SHA-256: `f820219b39e6869d4dee2b63e1a75fd0455339fba6b68c14323848b1125592b4`.
- New baseline ID: `ubuntu-noble-amd64-2026-09-28-v1`.

The policy test verifies that the new resolved list equals the original recorded baseline plus exactly this 163-package FFmpeg set. No host baseline phase was run; the overseer runs it after merge in a quiet window.

## Verification

- `bash tests/infra/test-os-baseline-policy.sh` — passed.
- `bash tests/infra/test-os-baseline-transaction.sh` — passed.
