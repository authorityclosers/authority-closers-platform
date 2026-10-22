# AUT-2197 — bounded prerequisite publication lifecycle

Scope: child output for [AUT-2188](/AUT/issues/AUT-2188), ready for CTO re-review. No installation, release, settings change, artifact deletion or production acceptance is included.

## Findings and implementation

The previous producer searched only successful main workflows. Before main bootstrap, independent workbench requests therefore uploaded the same 452 MB closure. During this repair, the first 100 repository artifact records contained nine same-identity bundles and 4,600,678,410 active artifact bytes. This is a lower bound from API inventory, not billed-quota evidence. Existing artifacts remain untouched.

Both application and workbench prerequisite jobs now share the repository-wide `ci-prerequisite-publication-v3` job concurrency group with cancellation disabled. Availability is checked after ownership, and ownership spans prepare, upload and reference generation. GitHub can replace a pending concurrency waiter; such a request can safely decline/cancel rather than publish a duplicate.

Successful trusted-main publications remain the preferred path. Before main publication, only the committed bootstrap pin file can authorize cross-run reuse. Each pin binds repository, locked-input identity, artifact ID and SHA-256, producer run and source SHA, plus reviewed source SHA. The producer must be a successful same-repository workbench push; its commit must have the reviewed source as its only parent and change only `.wb-ci/request.json`. Artifact API metadata, downloaded ZIP, manifest, payload and Debian closure remain verified. Matching sibling/PR artifact names do not grant trust.

The bootstrap file is deliberately excluded from the identity hash to avoid circular pinning: recording an exact reviewed publication must not invalidate its identity. Producer/acquisition code, action and lockfiles remain identity inputs. The existing reviewed cold run is recorded as a historical exact pin; it cannot match the new implementation's identity. The next identity needs its own reviewed pin before cross-run bootstrap reuse. A first producer can publish within admission bounds; a following unpinned fresh duplicate is refused until its pin is reviewed.

## Retained storage bounds and recovery

- Reserve **536,870,912 bytes (512 MiB)** before acquisition. Immediately before upload, re-read inventory and check that the two upload files plus 64 KiB of ZIP overhead fit the reservation.
- Projected retained prerequisite bytes must be at most **1,073,741,824 (1 GiB)**. Projected total active artifact bytes must be at most **1,610,612,736 (1.5 GiB)**. This leaves **512 MiB** relative to the reported approximate 2 GiB incident threshold; it is a conservative policy, not a guarantee about GitHub billing or concurrent unrelated workflows.
- At most **two active publications per identity**: bootstrap plus a bounded baseline/age recovery. A fresh unpinned existing artifact prevents another build/upload. A verified baseline solve failure can replace its exact artifact once. Expired artifacts do not count; age/near-expiry recovery remains subject to both caps.
- Inventory is paginated (100 pages maximum), must be complete before admission, and stops early when already over the cap. Missing inventory, authentication failures, malformed metadata, corruption and oversize payloads fail closed. No deletion or spending is used to make room.
- Bundle retention stays two days; workbench diagnostic retention stays one day. SHA/run-attempt and complete-file coverage aggregation is unchanged.
- These bounds apply to producers running this implementation. Older in-flight producers and unrelated artifact workflows are outside its shared lock. Existing retained bytes are never reclaimed by this change.

## Verification

Focused tests cover no-main exact bootstrap, foreign/corrupt producer rejection, reviewed-source relationship, simultaneous same-identity ownership/recheck, expiry/near-expiry/age and baseline recovery, inventory/auth/storage/size failures, full pagination, and admission immediately before upload. Existing cold/offline acquisition and retention tests are retained; the full hosted cold suite is not repeated.

Local final result and implementation pin will be recorded below. Initial verification caught two fixture mistakes (substring matching `per_page=100` as `page=1`, and expecting the identity cap before the earlier byte cap); both fixtures were corrected, preserving the stricter byte admission behavior.

## Historical reviewed cold publication

- Reviewed source: `c2ade062061f09ffdd4c7269d8d5858072000e2a`.
- Producer source: `adfc31e64dd539f37f4a4af507b433e00ad82cc1`.
- [Run 39837257389, attempt 1](https://github.com/authorityclosers/authority-closers-platform/actions/runs/39837257389/attempts/1).
- Artifact **12452071131**, **452,074,312 bytes**.
- Identity `f2f6966933d5e6ec94e1a7feeb383042af56a49258bc6f1c23887ccb04b8e38c`.
- ZIP SHA-256 `8f1e02fa0191f5e0e718e0ba88eda11959baf1a88fdb2d70ffbe38e0d43f463c`.
- This repair does not reinterpret that full cold proof or claim a new upload/reuse for the changed identity.
