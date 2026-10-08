# AUT-1420: exact dev billing runner preflight

Implementation baseline: `4440f44b1400aca089e4074ca1203c60e1984839`, admitted by
`ac-gate start devenv 1420-dev-billing-runner-preflight`; `ac-gate check` passed.
The checkout was clean before start. The earlier lane blocker has cleared.

The repair is limited to the root runner, its existing infra tests and this
operator handoff. It changes no application/fixture code, credential transport,
secrets, accounts, grants, billing state, services or network attachments.
Preflight injects no secrets and opens no database connection.

## Immutable executable handoff

Use the already published release
`b5e240d29d7a24e7c81d3183665fd88a9e144899`, rather than the missing local image
of `d5af14fc105a1e3539e3e9ba7fc058fc10eb8c44`. This is a reviewed source pin,
not a mutable tag or an image fallback. The runner verifies the root-owned
release directory and `RELEASE-FILES.sha256`; takes its exact config digest
from `release-images.env`; and requires Docker's image ID to equal that digest
and its OCI revision label to equal the pinned source. `--pull=never` remains.

[Ordinary application run 37311090246](https://github.com/authorityclosers/authority-closers-platform/actions/runs/37311090246)
was read back as a successful completed main push for exactly this SHA.
Packaging job `111773414724`, validation and capacity simulation succeeded.
Root's [earlier metadata receipt](/api/attachments/76dee6a5-afc7-45b6-afdd-485c49045e28/content)
already verified this stored release when installing the transport scripts.
Neither that receipt nor publication metadata proves that this API image is
currently local. Root must record that readback and the actual preflight; no
image availability or live success is claimed here.

The container probe checks the baked release ID, actual UID 10001, the fixed
staff identity/password-variable declarations, and these installed source
hashes (computed from the exact pinned Git objects):

| Module                                           | SHA-256                                                            |
| ------------------------------------------------ | ------------------------------------------------------------------ |
| `ac_platform.development.billing_qa_fixture`     | `8328ff61345b094be96acc8eaae685eeb3caa0e4a530fc97df3b1a63b7cb4a74` |
| `ac_platform.authorization.operator_data_change` | `96f585fb7a1489388835f71e56930870aa2666bdbc4918ae52e2829256e254d3` |
| `ac_platform.authorization.__main__`             | `4e264d8135dadcc2d00eabbc91e7e091335f778875261ed3e3e6516f9248eeb1` |

The fixture source differs from the old executable only by the already merged
tenant argument in `service.ledger(database, tenant_id=account.tenant_id)`.
This repair makes no fixture edit. Both pins' `require_target` ASTs hash to
`f6c9dfdc8fe7427bbbbbdc2870cabc2a16bb81dec4f3d492d7d3d3cfb8c3d846`.
Every data command still invokes that canonical guard before execution.

## Exact network selection

Only `acdev-xray` is selected. `acdev-postgres` must have exactly one attachment
with the approved IP `172.27.0.2`, and it must be the named network. Other
attachments with different endpoints may coexist; iteration order is irrelevant.
Missing/wrong/duplicate approved endpoints and malformed network metadata refuse.
The selected Docker network must use the `bridge` driver. The container probe
requires the complete DNS address set, including IPv6 answers, to equal the
single approved IPv4 address; missing, wrong or ambiguous DNS refuses.

The approved DB URL remains `postgresql+psycopg`, user `ac_runtime`, port 5432,
database `ac_platform`, with the unchanged hostname/PG/query/live-provider
guards. Credential selection, in-memory URL routing and fixture application
arguments are unchanged. Containers retain read-only root, UID 10001, no host
mounts/ports/capabilities, no new privileges, 256 MB, 0.25 CPU, 64 PIDs,
16 MB scratch, no Docker logs and automatic removal.

## Validation and remaining acceptance

Focused commands use fictional inputs and simulated infrastructure only:

```bash
uv run pytest tests/infra/test_dev_qa_credential_transport.py tests/unit/test_dev_billing_qa_fixture.py -q
uv run ruff check infra/application/scripts/dev-billing-qa.py tests/infra/test_dev_qa_credential_transport.py
uv run ruff format --check infra/application/scripts/dev-billing-qa.py tests/infra/test_dev_qa_credential_transport.py
git diff --check
```

Tests execute the probe against fictional module files and exercise source/UID/
module/DNS refusal, multi-attachment selection, missing images, wrong image IDs,
source/checksum/owner/driver refusal, secret-free preflight receipts, credential
containment and canonical fixture guards. Actual host evidence is separate.

Result: **179 passed in 7.23 seconds**, no skips. Focused Ruff check and format
passed; Markdown was formatted with Prettier. No Docker, Infisical or live
database command ran as part of these tests.

Root metadata child creation was rejected with HTTP 409; no child was created
and the write was not retried. The current source PR remains independently
reviewable. Root's recorded task and metadata/preflight output must exist before
this card completes. Sensitive CTO review, CEO SHA-bound approval, watchdog
merge, green CI and a stored immutable runner release precede installation.

## Root installation and rollback

Root is the only operator. Create/reuse a concrete Root installation task after
the source is approved and merged. Record the exact merged source, successful
CI run, immutable stored runner release and installed script readback there.
`runner_release` below must be the literal full SHA of that stored release,
containing the approved runner bytes. This source release is distinct from the
fixed API executable pin above. No checkout/laptop copy is an install source.

First verify the pinned executable release's root ownership, manifest, exact
`AC_API_IMAGE`, Docker image ID/revision and the DB/network metadata. Print only
`AC_RELEASE_ID` and `AC_API_IMAGE` from its manifest, never a service environment.
If that exact image is absent, stop and record its digest and absence. Do not
pull/build, select another release/tag, invoke a staging deploy to load an image,
or manufacture a recovery receipt. A separately scoped supported recovery or
reviewed new source pin is required in that case.

For the reviewed runner, run the following through Root's supported execution
path, after substituting the recorded full `runner_release` SHA:

```bash
set -euo pipefail
runner_release=REPLACE_WITH_RECORDED_IMMUTABLE_RUNNER_RELEASE_SHA
[[ "$runner_release" =~ ^[0-9a-f]{40}$ ]]
R="/srv/authority-closers/application/releases/$runner_release"
B="/var/lib/ac-root/task-backups/AUT-1420-$runner_release"
test -d "$R" && test ! -L "$R"
test "$(stat -c '%u' "$R")" = 0
test -z "$(find "$R" -maxdepth 0 -perm /022 -print)"
(cd "$R" && sha256sum --check --strict --quiet RELEASE-FILES.sha256)
test "$(sha256sum "$R/scripts/dev-billing-qa.py" | cut -d' ' -f1)" = \
  6f2dcc4599849e80cfd2977f7642f504430edf0e42de96ee582e2ee77e80e0e3
test -f /usr/local/sbin/ac-dev-billing-qa
test ! -L /usr/local/sbin/ac-dev-billing-qa
test "$(stat -c '%u:%g:%a' /usr/local/sbin/ac-dev-billing-qa)" = 0:0:700
test "$(sha256sum /usr/local/sbin/ac-dev-billing-qa | cut -d' ' -f1)" = \
  f47131e68dbfa87fd4c397abaf607b95f677619a2df38b6607db42b594f18335
test ! -e "$B"
install -d -o root -g root -m 0700 "$B"
cp -a -- /usr/local/sbin/ac-dev-billing-qa "$B/ac-dev-billing-qa"
install -o root -g root -m 0700 "$R/scripts/dev-billing-qa.py" /usr/local/sbin/ac-dev-billing-qa
cmp -- "$R/scripts/dev-billing-qa.py" /usr/local/sbin/ac-dev-billing-qa
python3 /usr/local/sbin/ac-dev-billing-qa preflight
```

Do not reinstall the two credential/browser scripts or sudoers: their previous
verified installation is complete. If the new runner is already installed,
verify its hash, owner/mode and existing backup instead of replaying installation.
For repeatability, a second separate `python3 /usr/local/sbin/ac-dev-billing-qa
preflight` must return the same release/image/network/UID/module hashes.
Retain both actual JSON outputs, exit codes, installed hash/mode, run identity
and cleanup readback on the Root task. Require `ok=true`, UID 10001,
`network=acdev-xray`, `database_ip=172.27.0.2` and all three module hashes.
No secret injection or inventory/fixture/owner/first-manager command is included.

On install/readback/preflight failure, preserve its receipt and restore only the
saved runner, using the same recorded `B`:

```bash
test -f "$B/ac-dev-billing-qa" && test ! -L "$B/ac-dev-billing-qa"
test "$(sha256sum "$B/ac-dev-billing-qa" | cut -d' ' -f1)" = \
  f47131e68dbfa87fd4c397abaf607b95f677619a2df38b6607db42b594f18335
cp -a -- "$B/ac-dev-billing-qa" /usr/local/sbin/ac-dev-billing-qa
cmp -- "$B/ac-dev-billing-qa" /usr/local/sbin/ac-dev-billing-qa
stat -c '%u:%g:%a' /usr/local/sbin/ac-dev-billing-qa
```

Rollback restores the recorded runner bytes and metadata; it does not change
an image, service, network or database. Inspect only names/state of any leftover
`ac-dev-billing-qa-*` container; never dump its environment or retry an unknown
outcome. Root retains any cleanup action in its own recorded operator task.

This card stays open until the merged/released runner and repeatable real
`ok=true` receipts are recorded. Its output unblocks
[AUT-959](/AUT/issues/AUT-959) and supplies
[AUT-1156](/AUT/issues/AUT-1156)'s dev acceptance. Neither downstream card is a
dependency of this implementation.
