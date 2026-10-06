# AUT-1366 governed native transition

Source implementation receipt, 6 October 2026. Host execution remains with
Root on [AUT-1361](/AUT/issues/AUT-1361), after sensitive review and merge.

## Integration choice

Use an engine preparation receipt to admit the exact stored native CI bundle;
the existing automatic core path installs its immutable helper and matching
activation, with the existing native supervisor installer and canonical
application-only rollback. Strict unchanged-input reuse remains in place.

The native installer gap is limited to an internal, reviewed renderer binding:
the current healthy core renderer can supervise the target helper before the
new core source exists. Both directions still verify renderer bytes, descriptor
hashes, artifact identity, canonical paths and exact rendered units. No new
standalone installation option is exposed.

Admission checks the ordinary main push and first run attempt, exact workflow,
repository/run/artifact/source identities, expiry, ZIP size/digest and complete
checksums, committed recipe/helper inputs, OCI index/manifest/config/layers,
image environment bindings and approval lifetime/hash. Preflight verifies the
prior unit descriptor, live units, immutable helper/image and healthy core,
equal migration heads, backup support and reviewed rollback controller. Missing
or changed proof refuses before runtime mutation.

Preparation preserves running units/links, activation publication, flags and
approval bytes. Non-dry preparation saves a pinned engine receipt only. Automatic
deployment checks those pins again, records rollback identities before loading
the image, and publishes activation from permanent operator inputs. A later
helper, activation, installer or readiness failure restores the old helper and
units before canonical core rollback, verifies the old activation/core, and
keeps staging paused/failed. Recovery failure keeps containment and records no
successful core restoration. Both core bundles are retained by transition pins.

## Verification

The focused release/native suites use fictional CI bundles, OCI transports,
unit descriptors, approvals and fake systemd/Docker/core delivery adapters.
They cover changed workflow input admission, mismatched/expired/incomplete
provenance, unchanged-input reuse, approval preservation, preparation vs live
installation, dry-run publication/runtime/flag invariance, helper failure,
activation failure, core failure before/after switching source, readiness
failure, restoration identities and order, failed recovery and rollback
retention. The installer tests exercise real descriptor/rendering checks in
both directions and refuse an unreviewed renderer.

Final local receipts:

- `uv run pytest -q tests/infra/test_ac_release.py tests/infra/test_sales_xray_native_installer.py tests/infra/test_ac_release_foundation_install.py tests/infra/test_ac_release_train.py tests/infra/test_ac_release_admin.py tests/unit/test_prepare_sales_xray_native_activation.py tests/unit/test_native_artifact_compatibility.py`: **448 passed**, 115.07 seconds.
- `uv run ruff format --check packages/python tests infra/release/ac_release.py infra/application/scripts/install-sales-xray-native.py`: **1040 files formatted**.
- `uv run ruff check packages/python tests infra/release/ac_release.py infra/application/scripts/install-sales-xray-native.py`: **passed**.
- `uv run mypy packages/python`: **passed**, 429 source files.
- `git diff --check` and latest-main `ac-gate check`: **passed**.
- `python3 infra/release/ac_release.py prepare-native --help`: staging-only command and both predecessor pins present.

Ordinary CI and exact PR/head review receipts belong on the source issue. No
real provider, customer or database calls were made.

## Root handoff

The exact command sequence and refusal/rollback checks are in
[RELEASE_ENGINE.md](../runbooks/RELEASE_ENGINE.md#pause-preserving-engine-bootstrap-and-exact-recovery-handoff).
It uses the existing clean-source installer under `/run/ac-release.lock` while
staging remains paused; it never edits installed engine files by hand. Root
must bind that installation to the reviewed merged commit and green ordinary
CI identity, record prior engine SHA/hash and flag bytes, and verify unchanged
flags/core/web afterward. Rollback uses the same installer from the previous
exact clean source. The existing Root parent owns this supported installation;
no additional permission or diagnosis task is needed.

Recovery target remains `386f28ba6f046fd2dda1727ca6736f9260f79709`. Root supplies
the actual predecessor unit path/hash from its successful installation receipt,
then runs exact `prepare-native --dry-run`, `prepare-native`, and core
`deploy --dry-run`. Only after those checks may the parent use its authorized
resume and the existing timer. The retained native record expires at
`2026-10-06T23:18:36Z`; admission never treats a retained ZIP as permission to
ignore provenance expiry. A refusal preserves containment.

This source card authorizes no staging/production operation, service edit,
engine installation, pause clearing, CI rerun/build or approval replacement.
Source completion requires reviewed merged green source and its exact Root
handoff; approval alone is not completion. Root owns installed capability and
the ultimate live staging recovery proof.
