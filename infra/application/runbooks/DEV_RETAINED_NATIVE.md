# Development retained native transition

Source card: [AUT-1473](/AUT/issues/AUT-1473). Host operator:
[AUT-1469](/AUT/issues/AUT-1469). This runbook supplies no installation grant.
CTO source review and CEO merge approval precede release. Root must also have
the specific recorded development-native grant on AUT-1469 before apply.

Run the **released** `scripts/prepare-dev-sales-xray-native.py` from the merged
source SHA C recorded on AUT-1473. Its own controller, installer, compatibility
verifier and unchanged refresh helper are checked against C's committed blobs
and installed `RELEASE-FILES.sha256` before import. Do not execute a checkout,
copy scripts into a release, or change the selected core to obtain a renderer.
Normal application archive packaging includes this operator. The archive
verifier requires it; there is no separate host script copy/install step.

The native renderer comes from the already installed target core T. Its file
mode and blob must equal the renderer committed by native artifact N, and its
SHA-256 must be the reviewed
`88f6e50960566c61d780e9fc2370c61c2db17c818c7d2c5963a8974ef70eec76`.
The rendered descriptor and service prestart explicitly name T's renderer.
This binding is confined to the new supported development operator; ordinary
installer candidate checks and staging/production commands stay unchanged.

## Audited inputs from 7 October

| Input                              | Identity                                                                  |
| ---------------------------------- | ------------------------------------------------------------------------- |
| T                                  | `1c06c4af14222a9de71334b25f3e373cf1fa4906`                                |
| N                                  | `386f28ba6f046fd2dda1727ca6736f9260f79709`                                |
| Ordinary main-push run, attempt    | `37387436215`, `1`                                                        |
| Retained artifact                  | `11379402384`                                                             |
| Immutable ZIP SHA-256              | `ec5b2e56c39b2497a3dcb11937863424fb503c00e714c5873e9f288216bc4d74`        |
| Native manifest SHA-256            | `490292f3e0bdf5a95448e35c8318979d5d36ecca86fdc51c901ac77209b2978c`        |
| Reuse input SHA-256                | `03e1098a325c1fc2142464f9ae01615ac009e64e2146534f49bdb077d4453592`        |
| Artifact metadata SHA-256          | `5a11c1c5530bab1e0e610e5bcc8e794ac0bdcbae694543635f486e79e09c5a9a`        |
| Workflow record SHA-256            | `82f32a7d3b715d7741e0ef5a8bba6d7cea49d9883f7a04d5387aef9a47300f05`        |
| Image reference                    | `sha256:3eb09b14990ee651c0f335a7397badc2730cec8f3df5904b9a94a5e011250f31` |
| Image config                       | `sha256:68ec56ff10322f4d6cd765603f9e6b07c45189c327a60ad7a714c728bfd34cd9` |
| N0                                 | `1e784afa128f8d4629aeece5179486d423c0ec52`                                |
| Previous descriptor SHA-256        | `cd58ce416637aff59040ecc073c38c861767b3181cc2a48861eb8cb692ec4e15`        |
| Previous manifest SHA-256          | `b477e4b1714dffd84d5e1427b63f020aacfb8b2f51281484ce14f668af9ebbd5`        |
| Historical install receipt SHA-256 | `38289d4fa9bc6703543cba6888d8970973ad1025f49543d8fd3ca69f08506f55`        |
| Unchanged refresh helper SHA-256   | `1dabe645d9e42f9004c401118c26c4077e57c856aa7a828f39a839109201e2fc`        |

The historical receipt is provenance, **not** the current rollback snapshot.
Each preparation independently pins current unit, descriptor, client and
protected file bytes/metadata and current runtime states.

## Dry-run and preparation

Root verifies C and its immutable script hashes against the final source
handoff first. Run the following argv using C's full released SHA as the two
`<C>` values. The default is read-only dry-run. Both existing release locks are
opened without creation and acquired without waiting. A busy/missing/untrusted
lock refuses before publication.

```sh
/usr/bin/python3 /srv/authority-closers/application/releases/<C>/scripts/prepare-dev-sales-xray-native.py \
  --source-sha <C> \
  --target-core 1c06c4af14222a9de71334b25f3e373cf1fa4906 \
  --native-reuse-proof /srv/authority-closers/application/operator-inputs/staging/native-1c06c4af14222a9de71334b25f3e373cf1fa4906-acfb702d4d2f714e/inputs/native-reuse-input.json \
  --native-reuse-proof-sha256 03e1098a325c1fc2142464f9ae01615ac009e64e2146534f49bdb077d4453592 \
  --native-artifact-sha256 490292f3e0bdf5a95448e35c8318979d5d36ecca86fdc51c901ac77209b2978c \
  --previous-native-units-sha256 cd58ce416637aff59040ecc073c38c861767b3181cc2a48861eb8cb692ec4e15 \
  --previous-manifest /srv/authority-closers/application/artifacts/sales-xray-native-1e784afa128f8d4629aeece5179486d423c0ec52/native-image.json \
  --previous-manifest-sha256 b477e4b1714dffd84d5e1427b63f020aacfb8b2f51281484ce14f668af9ebbd5 \
  --previous-receipt /srv/authority-closers/application/deployments/development/native-unit-install-aut-119-20261002T1516.json \
  --previous-receipt-sha256 38289d4fa9bc6703543cba6888d8970973ad1025f49543d8fd3ca69f08506f55
```

Done check: exit 0, `status=dry_run`, 14 compatible mode-and-blob inputs, exact
run/artifact/image identities, no runtime mutations. No storage/import/rebuild
is needed: both candidate and rollback images must already be installed.
The refresh service/timer must already be inactive; the operator never stops
or reconfigures them. An active timer is a separate recorded Root step.

Repeat the same argv with:

```sh
--prepare /srv/authority-closers/application/operator-inputs/development/native-plan-aut-1473.json
```

Done check: exit 0, `status=prepared`, record the returned `plan_sha256`. The
new root-owned, non-writable plan contains hashes/metadata only. The operator
does not print environment contents, credentials, approval contents or provider
tokens. Do not upload the private rollback files described below.

## Apply and publication contract

After the recorded development-native grant, repeat the dry-run argv with:

```sh
--apply \
--prepared-plan /srv/authority-closers/application/operator-inputs/development/native-plan-aut-1473.json \
--prepared-plan-sha256 <PREPARED_PLAN_SHA256> \
--receipt /srv/authority-closers/application/deployments/development/native-transition-aut-1473.json
```

Apply repeats every preflight and requires the pinned plan to match, including
all current predecessor/client/protected inputs. It persists exact current
rollback bytes, metadata and states in the root-only `0700` sibling directory
`native-transition-aut-1473-rollback` before stopping a service. Backup files
are `0600`. Only the sanitized plan and receipt may be attached to the issue.

The reviewed client renderer changes only:

- `AC_SALES_XRAY_NATIVE_IMAGE_REF` in `api.env`, preserving every other byte;
- `native_image_ref` in `service.json` and `service.operator-template.json`,
  retaining every other field and the serving backend release;
- the corresponding worker manifest SHA-256 drop-in.

API and worker drain only when their native image binding changes; outbox is
never restarted. Native drain must be verified before any publication. While
consumers are stopped, publish unit and client bytes/metadata and the matching
native descriptor; reload systemd; activate the mount before the native helper;
verify units, sandbox/private socket, then restore the prior API/worker active
states. Restore prior enabled states; do not enable previously disabled clients.
This is a transaction at the drained-consumer boundary, with fsynced atomic
renames for each file, rather than a filesystem-wide multi-file atomic rename.

All approval bytes, provider/storage/identity fields, AUT-1083 inputs, outbox,
refresh timer, UI checkout, backend checkout/release marker, and staging and
production pointers are checked for preservation. No backend refresh, DB
migration, provider/analysis request, credential creation, approval reseal,
account change, image import or staging/production write is part of this route.
Starting the existing worker restores its ordinary runtime; this command does
not enqueue or select a call.

## Verification and failure contract

Success requires exit 0, `status=installed`, `native_guard=PASS`, matching
descriptor/client/unit bytes, private native socket/readback, previous runtime
states, readiness at the **unchanged serving backend SHA**, and exact protected
state equality. The published descriptor must then independently pass Root's
existing released helper invocation:

```python
helper.check_native(helper.Paths(), helper.command, T)
```

Use T above; never change the helper pin, input inventory, descriptor helper
identity, or guard to obtain PASS. This completes the native prerequisite only;
AUT-1452 owns the separately authorized backend refresh.

On publication, reload, native startup, client binding, readiness, guard or
receipt failure, drain consumers before restoring exact predecessor files and
metadata, reload, restore native byte/state bindings, then restore previous
client states and verify protected state, live bindings and readiness. A failed
initial stop publishes nothing. A failed rollback stop also never rewrites
files beneath a live consumer. Record `rollback=completed` or `rollback=failed`
and the private backup location. If rollback fails, Root owns recovery from
the pinned backup on AUT-1469; do not rerun or hand-edit live inputs.

The source task does not claim host installation or dev completion. Record
Root's real apply/verification receipt on AUT-1469 under its specific grant.
