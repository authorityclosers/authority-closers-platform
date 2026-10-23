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

## Final implementation and focused checks

Implementation: **`62cc4b141ac7aa0994885fdc990197aa6bfd655b`**. Eight owned repository paths committed with the Paperclip trailer. Foreign workbench changes were preserved.

- **92 focused tests passed in 7.42 s**, including all existing prerequisite/bundle/retention tests and the new publication lifecycle cases.
- Ruff lint/format, Prettier, required `import ac_platform.http`, Bash syntax and owned diff whitespace passed. Both hosted lint jobs passed.
- Real read-only GitHub verification accepted the historical bootstrap pin's exact successful run, reviewed parent, request-only source difference and artifact digest metadata. Its existing cold ZIP/closure/Chromium proof remains the parent evidence; this repair did not download another 452 MB ZIP.

## Hosted simultaneous safe-refusal proof

New identity: **`f60a53a0e435ac6e06f73f0351c1b5c5a22a95de0893544f4a3d18c7166fc568`**.

| Request                                                                                                           | Attempt | Producer job | Producer interval (UTC, 22 Oct 2026) | Artifacts uploaded |
| ----------------------------------------------------------------------------------------------------------------- | ------- | ------------ | ------------------------------------ | ------------------ |
| [39841723696](https://github.com/authorityclosers/authority-closers-platform/actions/runs/39841723696/attempts/1) | 1       | 120044325700 | 19:37:46–19:38:12                    | **0**              |
| [39841746682](https://github.com/authorityclosers/authority-closers-platform/actions/runs/39841746682/attempts/1) | 1       | 120044511173 | 19:38:14–19:38:48                    | **0**              |

Exact request SHAs: `971474db195a3f5037486cd9707778f904d0312d` and `906223e37daa042d3d2fb190f4c4ecd5976e825b`. Each has implementation `62cc4b14` as its sole parent and differs only at `.wb-ci/request.json`; the bare-repository tree comparison and GitHub head metadata both confirm this. Producer intervals do not overlap. Both requests were started simultaneously through the committed source launcher, with separate retained slots.

Both producers logged the exact new identity under shared ownership and then:

```text
storage admission declined: retained_artifact_bytes=4950391106,
retained_bundle_bytes=4520764628, reserve_bytes=536870912;
wait for expiry or use the approved storage path; no upload or deletion
```

Neither producer reached signed Ubuntu acquisition. GitHub artifact API results for each run show `total_count=0`. Thus the repeat/concurrent proof safely declines without another 452 MB upload. No new publication ID or digest exists for this identity. Overall workflows and dependent summary jobs are intentionally red because publication was safely refused; they are not green cold/warm-consumer proofs. Lint is green in both runs. No full cold suite or old warming mutation was repeated.

During dispatch the second request's independent slot push succeeded while its shared `wb-ci-base` update reported a ref race: that ref already held the exact requested source. Both requested slot heads and hosted runs were verified; no retry, unrelated launcher repair or state change was needed. Direct job-log endpoint reads were unavailable; `gh run view --attempt 1 --log-failed` successfully retrieved the completed logs. All final claims use those logs and source/attempt-specific metadata.

The required child output is delivered for CTO re-review. Existing excess storage is unchanged and can still prevent CI/release publication. Authorized expiry/storage handling, integration/release approval, production version and seven-day reliability stay with the parent. Installed launcher refresh stays with [AUT-2190](/AUT/issues/AUT-2190); this child authorizes no install or deployment.
