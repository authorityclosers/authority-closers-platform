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
non-destructive rollback. A dedicated `--preserve-studio` refresh retains the
owner's active UI checkout while preserving existing backend release selection,
identity/native admission, migration, health and automatic rollback. The
scheduled refresh's default behavior is unchanged.

## Source verification, 6 October 2026

| Check | Result |
| --- | --- |
| Task lane: `ac-gate status`, `python3 scripts/ac_task.py check` | Own branch may continue; main green at initial check |
| Focused runtime/HTTP/infra plus settings/local avatar regressions | 378 passed in 87.35 seconds |
| Ruff format check and lint for all changed Python files | Passed |
| `mypy packages/python` | Passed, 431 source files |
| `docker compose -f infra/application/development/organisation-avatar/compose.yaml config --quiet` | Passed; render only |
| `systemd-analyze verify` for the scanner unit | Passed; no service started |
| `sh -n` for the scanner wrapper; `git diff --check` | Passed |

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

## Release and live acceptance

No host unit, environment file, account, database or deployed UI was changed in
this implementation run. CTO review, CEO SHA-bound merge approval and CI remain
release prerequisites. Root owns the dedicated installation steps in
[`organisation-avatar/README.md`](../../infra/application/development/organisation-avatar/README.md),
then the actual fictional PNG PUT/WebP/restart/role/isolation acceptance on
AUT-1285. Reuse the existing fixture credentials through runtime injection and
preserve its two successful details audit events. Do not close AUT-1416 on code
approval: the reviewed runtime must work on dev before completion.
