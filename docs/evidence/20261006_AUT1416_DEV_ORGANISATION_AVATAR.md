# AUT-1416 — supported persistent development organisation logos

Source branch: `task/devenv/1416-dev-organisation-avatar`, resumed from
`0323629b5ac721e1bee020fa7636a380d1cef536`. The CEO's 6 October continuation identifies the interrupted
settings, HTTP, runtime, infrastructure and test changes as this task's work.

The reported dev failure was a fictional admin PNG PUT returning
`503/media_storage_unavailable` on core `ce753781ba69f9b2e74b9300619473173bab2be1`.
The existing deployment filesystem profile refuses development; the local
profile requires its separate managed sandbox. This change adds an independent,
default-off development organisation logo composition instead of weakening
either guard or activating video/provider media.

The new Settings opt-in requires development, the exact dev-only private store
and scanner paths, and no other media activation. Composition rechecks admission,
directory ownership/mode, link refusal and the private scanner's metadata. It
reuses the reviewed immutable avatar storage, 512px WebP sanitization and bounded
ClamAV scanner. Only organisation routes receive the additional runtime.

The separate scanner profile pins the existing reviewed ClamAV image and limits
CPU to 0.5, memory and swap to 1536 MiB, PIDs to 32 and temporary storage to
16 MiB. No port or foreign environment storage is exposed. Its source-owned
startup proof checks actual container mounts/resources, config hashes, PING,
clean and harmless EICAR INSTREAM verdicts, loaded daily signature identity and
a 48-hour freshness limit. The wrapper clears only its own socket on restart.

The Root runbook provides installation, API activation, verification and
non-destructive rollback. The dedicated sibling
`refresh-dev-sales-xray-backend-only.py` retains the owner's active UI checkout
while reusing the pinned helper's release selection, identity/native admission,
migration sandbox, health and automatic rollback. It loads that helper at
SHA-256 `1dabe645d9e42f9004c401118c26c4077e57c856aa7a828f39a839109201e2fc`,
the same pin as the approval reseal tool. Neither the scheduled helper nor the
reseal tool is modified.

## Initial local verification, head e94b49e, 6 October 2026

| Check                                                                                             | Result                                               |
| ------------------------------------------------------------------------------------------------- | ---------------------------------------------------- |
| Task lane: `ac-gate status`, `python3 scripts/ac_task.py check`                                   | Own branch may continue; main green at initial check |
| Focused runtime/HTTP/infra plus settings/local avatar regressions                                 | 378 passed in 87.35 seconds                          |
| Ruff format check and lint for all changed Python files                                           | Passed                                               |
| `mypy packages/python`                                                                            | Passed, 431 source files                             |
| `docker compose -f infra/application/development/organisation-avatar/compose.yaml config --quiet` | Passed; render only                                  |
| `systemd-analyze verify` for the scanner unit                                                     | Passed; no service started                           |
| `sh -n` for the scanner wrapper; `git diff --check`                                               | Passed                                               |

The test command was:

```sh
.venv/bin/pytest -q --tb=short \
  tests/unit/media/test_development_organisation_avatar_runtime.py \
  tests/unit/http/test_organisation_settings.py \
  tests/infra/test_dev_organisation_avatar.py \
  tests/infra/test_refresh_dev_sales_xray_backend.py \
  tests/unit/application/test_settings.py \
  tests/unit/media/test_local_avatar_runtime.py
```

HTTP tests exercise both local and development compositions: fictional owner
and admin saves; fresh-store reopening; metadata stripping and WebP delivery;
anonymous/member denial; known-logo cross-organisation 404; replacement and
idempotent replay; wrong-type, oversized and invalid image rejection; scanner
rejection/error; and canonical settings/audit preservation. ClamAV replies and
host metadata are simulated in source tests; they are not live dev evidence.

## CTO revision, 6 October 2026

The first head `e94b49eb0dc922cd04ca5c27966f67ab73b7a32e` changed the
scheduled refresh helper. CI shard 0 exposed the approval reseal tool's immutable
helper pin at collection. The revision restores both the helper and its tests
to the task base; the reseal tool and all its private-delivery digests stay
unchanged. Route chosen: a separately tested, digest-pinned sibling for Root's
recorded backend-only refresh, preserving the active UI checkout.

CI shard 3 also exposed a test fixture dependent on umask: `mkdir(mode=0o755)`
became `0700` under CI's private umask. The unsafe-directory test now sets `0755`
explicitly before checking refusal. Runtime ownership and permission gates are
unchanged.

Revision verification:

| Check                                                                    | Result                                                                                                                                                            |
| ------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Combined focused suite under `umask 077`, including approval reseal      | 797 passed, 1 skipped in 115.61 seconds                                                                                                                           |
| Sibling tests                                                            | 13 passed; pin refusal before execution, admission before mutation, UI preservation, private migration sandbox, no-op, failure rollback and dirty-backend refusal |
| Ruff format check and lint for revision Python files                     | Passed                                                                                                                                                            |
| Scheduled helper, original helper tests and reseal tool versus task base | Byte-identical                                                                                                                                                    |
| Normalized AST comparison of backend flow through health/rollback        | Matches the pinned helper, apart from the preserved-UI receipt field                                                                                              |
| `git diff --check`                                                       | Passed                                                                                                                                                            |

The revision test command was:

```sh
umask 077
.venv/bin/pytest -q --tb=short \
  --basetemp "$PAPERCLIP_RUN_SCRATCH_DIR/pytest-aut1416-revision" \
  tests/unit/media/test_development_organisation_avatar_runtime.py \
  tests/unit/http/test_organisation_settings.py \
  tests/infra/test_dev_organisation_avatar.py \
  tests/infra/test_refresh_dev_sales_xray_backend.py \
  tests/infra/test_refresh_dev_sales_xray_backend_only.py \
  tests/infra/test_reseal_dev_sales_xray_approval.py \
  tests/unit/application/test_settings.py \
  tests/unit/media/test_local_avatar_runtime.py
```

The one skip is the existing Root-only, isolated fictional systemd reseal proof;
this revision does not change that tool or rerun its host operation. GitHub CI
must validate the revised head before merge. Source tests and the AST comparison
do not substitute for the recorded Root installation and actual dev acceptance.

## Release and live acceptance

No host unit, environment file, account, database or deployed UI was changed in
this implementation run. CTO review, CEO SHA-bound merge approval and CI remain
release prerequisites. Root owns the dedicated installation steps in
[`organisation-avatar/README.md`](../../infra/application/development/organisation-avatar/README.md),
then the actual fictional PNG PUT/WebP/restart/role/isolation acceptance on
AUT-1285. Reuse the existing fixture credentials through runtime injection and
preserve its two successful details audit events. Do not close AUT-1416 on code
approval: the reviewed runtime must work on dev before completion.

The CEO has already placed AUT-1440 and AUT-1441 under AUT-63 and assigned Root;
both remain backlog and AUT-1441 retains its scanner dependency. After merge and
the build is on dev, Dev Environment Lead moves AUT-1440 to todo. No board or
owner action is pending for those assignments.
