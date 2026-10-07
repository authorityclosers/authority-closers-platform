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

Initial focused validation:

- `uv run --no-sync pytest -q tests/infra/test_prepare_dev_sales_xray_native.py -k 'descriptor or dry_run or success' --maxfail=1`: **16 passed**.
- Ruff check and formatting pass for the new operator and tests.
- `git diff --check`: PASS.
- Unchanged refresh helper SHA-256:
  `1dabe645d9e42f9004c401118c26c4077e57c856aa7a828f39a839109201e2fc`.

Fixtures are generated fictional CI bundles and isolated Git repositories.
No Docker/systemd/host installation, customer audio, provider call or database
write occurred. The successful-transition fixture calls the actual unchanged
refresh helper against the newly published descriptor and fixture Git objects.

Final focused regression counts and source handoff hashes are recorded before
review submission. CTO review, CEO approval and the recorded Root grant on
[AUT-1469](/AUT/issues/AUT-1469) remain required; this source evidence does not
claim host completion. Operator argv and rollback checks are in
`infra/application/runbooks/DEV_RETAINED_NATIVE.md`.
