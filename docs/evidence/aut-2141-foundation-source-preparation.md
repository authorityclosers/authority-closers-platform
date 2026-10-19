# AUT-2141 — foundation-contained encrypted Drive candidate source

Source preparation only for [AUT-2138](/AUT/issues/AUT-2138). The candidate remains uncorrected and unadmitted; no live encryption or database restore is claimed.

## Exact source

Candidate commit: `62ed2bdb715acca37268bc0807eb38117469028e`. Both new canonical files are byte-for-byte copies of their original `scripts/ops/` paths at that commit, with no mechanical path adjustment. They are regular Git mode `100644` files inside `infra/vps-foundation/scripts/`, with no symlink or hard-link escape. Original helper, wrapper and fictional tests are unchanged.

| Canonical source | Bytes | SHA-256 |
| --- | ---: | --- |
| `infra/vps-foundation/scripts/drive_postgres_backup.py` | 14246 | `f1f2d5e53b7fdde542f6f6a1ea5ccc1a35ebe6b9f98c234f6739afbd7b383dcc` |
| `infra/vps-foundation/scripts/drive-db-snapshot` | 2636 | `9bdefa32d870b3a7f7e64fbfde1a402bf02ec8271b13b4cc11fbe008f41a3ba2` |

Original fictional tests: `tests/infra/test_drive_postgres_backup.py`, SHA-256 `af0539c79c33996b0fcb9ac973a6f2dce2c70645623b1cff6342ebfa45b5c79a`.

## Verification

- `uv run pytest -q -p no:cacheprovider --basetemp <run-owned scratch>/pytest tests/infra/test_drive_postgres_backup.py`: **23 passed**, exit 0. Real GnuPG with fictional data and mocked transport; no external provider or real call data.
- `uv run ruff check infra/vps-foundation/scripts/drive_postgres_backup.py`: pass, exit 0.
- `uv run ruff format --check infra/vps-foundation/scripts/drive_postgres_backup.py`: pass, exit 0.
- `bash -n infra/vps-foundation/scripts/drive-db-snapshot`: pass, exit 0. The wrapper was not executed.
- `uv run python -c "import ac_platform.http"`: pass, exit 0.
- Exact pinned bytes, original-file preservation, regular-file type and link count: pass.
- Every existing `infra/vps-foundation/config/release/` file remains byte-identical to its pre-edit baseline. Neither the install manifest nor the backup scope contains the candidate helper/wrapper. No installer, manifest, scope, systemd unit or activation hook was changed.
- After commit, a local exact-commit `git archive` of `infra/vps-foundation` will be checked with the existing trusted archive verifier and each canonical member compared to the pinned source. The commit/archive receipt is retained on the task.

Raw logs, commands, exit codes and SHA-256 receipts are retained in the run evidence bundle attached to [AUT-2141](/AUT/issues/AUT-2141).

## Ownership handoff and next step

After the preparation commit, Root explicitly transfers the original helper, wrapper, fictional tests and both canonical files to Platform through `/home/acdev/strikes/2138/INBOX.md`. Root retains parent host execution ownership under [AUT-2133](/AUT/issues/AUT-2133) and [AUT-63](/AUT/issues/AUT-63).

Platform owns correction and integration with its process primitive at `53d372f8a3b32d0846350130f204e47df4c2114a`, subsequent transactional installer/manifest work, and the reviewed activation packet. Those paths were not edited here. The existing consumer repair and [AUT-2130](/AUT/issues/AUT-2130) → [AUT-2131](/AUT/issues/AUT-2131) remain with their existing owners.

No host command, credential access, network transport, release, deployment, timer change or production data change was performed. Rollback, if source preparation must be withdrawn, is a new ownership-coordinated commit removing only these two unadmitted copies; never reset shared work or replay host operations.
