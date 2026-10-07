# AUT-1473: retained development native source repair

Source scope: native operator, ordinary application archive packaging, Root
runbook and focused infrastructure tests. No overlap with open PR files was
found at task admission. The gate started `task/devenv/1473-retained-native`
from green main `1c06c4af14222a9de71334b25f3e373cf1fa4906` and permitted work.

The supported released operator admits a retained ordinary-CI native artifact
without installing its source core. The installed target renderer is verified
against both source commits, reviewed hash and installed release inventory.
Its supervisor binding is derived by code; the ordinary installer CLI has no
new override. The explicit development client renderer retains all protected
values and changes only native image bindings and the worker manifest digest.
Drained-consumer publication includes descriptor, units and client files, with
current exact byte/metadata/state backups before mutation and rollback on
failure. Default dry-run publishes nothing.

Initial validation (PR head `4e900c4`, before the CTO repair below):

- Native installer/supervisor, compatibility, application archive and release guards: **233 tests passed** as part of the 294-test focused regression run.
- Final development operator suite: **69 tests passed** after the final stop and Git-filter checks.
- Dry-run invariance, supported CLI preparation/apply, source and renderer provenance, every publication target, stop-before-publish, mount/socket/client startup, readiness, guard and receipt rollback, adopted credentials, sandbox/root identity, stale plans and protected-state preservation are covered.
- Ruff check and formatting pass for the new operator and tests.
- `git diff --check`: PASS.
- Unchanged refresh helper SHA-256:
  `1dabe645d9e42f9004c401118c26c4077e57c856aa7a828f39a839109201e2fc`.

Fixtures are generated fictional CI bundles and isolated Git repositories.
No Docker/systemd/host installation, customer audio, provider call or database
write occurred. The successful-transition fixture calls the actual unchanged
refresh helper against the newly published descriptor and fixture Git objects.

Read-only dev verification: `/health/ready` returned `ready` at serving backend
`ce753781ba69f9b2e74b9300619473173bab2be1`. No host state changed.

Initial immutable source file hashes (the operator hash is superseded below):

- `prepare-dev-sales-xray-native.py`: `97936a071dc4dda4f0d7276a85c99c18bfabd6c10c41dd1275f350331ac5849f`.
- `install-sales-xray-native.py`: `fa0769bf816b182b633d2a84370084a9f2c9ab3bcd572c62c0cbe2cbf47aeed0`.
- `native_artifact_compatibility.py`: `f822d7a4052e54cab30df28a0b00c6de9a6bdfd5bcfbf7d4f92f7e24997bebab`.
- `render-sales-xray-native.py`: `88f6e50960566c61d780e9fc2370c61c2db17c818c7d2c5963a8974ef70eec76`.
- `verify-release-archive.py`: `f595b187a93f2dcc032795b01d1e81cf40449e15b9bd700be71b4a01b62e92ac`.

The merged, released source SHA C is recorded after the merge/release event;
the task branch SHA is not represented as a released source. CTO review, CEO
approval, released-source verification and the recorded Root grant on
[AUT-1469](/AUT/issues/AUT-1469) remain required; this source evidence does not
claim host completion. Operator argv and rollback checks are in
`infra/application/runbooks/DEV_RETAINED_NATIVE.md`.

## CTO changes-requested repair, 7 October

The CTO reproduced root command execution through a clean filter defined in
an acdev-owned UI checkout's included Git config. The old `--local` filter
inventory omitted both `include.path` and `includeIf`, and adding includes
would still allow a config change between inventory and status.

The repair uses the CTO's supported ref-only option: UI inspection reads
HEAD and its loose or packed branch ref directly through bounded, regular-file,
no-follow reads. It does not run Git or inspect UI config, attributes, filters
or index. Detached HEAD is supported; malformed refs, traversal and symlinks
are refused. The Git helper also rejects checkout commands outside the
root-owned backend and validates the backend Git directory's ownership and
permissions before spawning Git.

The plan retains the UI HEAD/branch pin and drops its status hash. The Root
runbook now requires a quiet UI lane from preparation through apply/rollback:
a commit or branch switch invalidates the plan; an ordinary studio file save
does not affect this ref pin. The operator never writes the UI checkout.

Regression tests generate a separate fictional studio checkout. Local,
`include.path` and `includeIf` clean filters each execute in an ordinary,
unprivileged Git-status positive control, then cannot execute during the real
protected-state inspection. The tests also verify no process is spawned for
loose/packed/detached ref reads, no checkout bytes change, unsafe ref inputs
are refused, and the Git helper refuses the UI checkout before subprocess use.

Final repair validation: **81 native operator tests passed** with no skips,
including the existing dry-run, successful transition, CLI and full rollback
matrix. Ruff, Python/Markdown formatting, `git diff --check` and the current
main gate passed. No changes were made to the archive list or the other
native/release sources covered by the initial 233 related regression tests.

Current operator SHA-256, superseding the initial hash above:
`4447a66868a3daca749a9a4a2235bec731e7dd1799e52d9c3bc06ce7cba97e3e`.
The refresh helper and all other immutable source hashes above are unchanged.
The read-only dev readiness check again returned HTTP 200, `ready`, serving
`ce753781ba69f9b2e74b9300619473173bab2be1`. Host apply remains on
[AUT-1469](/AUT/issues/AUT-1469) under its specific grant.
