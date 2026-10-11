# AUT-1355: exact-source ship workflow repair recommendation

The operator should pair missing-web dispatch in `ac-ship` with a narrowly
defined exact-source web-dispatch admission in the release engine. Dispatch
alone satisfies the installed ship loop but does not make the resulting web
build discoverable by the installed engine. This is a recommendation, not an
installed repair or authorization to change the running ship.

## Original observed source and result

Release v0.41.0 is pinned to
`70000783a9bbe7f9b21523f978f04a7d3084a83e`. Its delta from v0.40.0
`fa846dc1264130e295eccc13daf6164c673c8a8a` changes four native/Python test
paths, with no Sales Xray web-image push input. The web workflow's existing
`workflow_dispatch` accepts `frozen_sha` and verifies checkout, image identity,
release marker, health, transport and artifact admission.

The coordinator's first exact-source web run
[38182582161](https://github.com/authorityclosers/authority-closers-platform/actions/runs/38182582161)
completed successfully at 23:02:49 UTC on 11 October 2026. Its event is
`workflow_dispatch`, head branch is `main`, and head SHA is the release SHA.
All image/source/health/transport/upload steps succeeded. GitHub reports:

| Field              | Value                                                                     |
| ------------------ | ------------------------------------------------------------------------- |
| Artifact ID        | `11718458319`                                                             |
| Name               | `ac-sales-xray-web-70000783a9bbe7f9b21523f978f04a7d3084a83e`              |
| Bytes              | `100165451`                                                               |
| Expired at capture | `false`                                                                   |
| GitHub digest      | `sha256:244de3b0e65fb0c1db092a62eb5da7131e5cb845d5c380efbf155db2cbe01176` |

Read-only replay uses the installed engine's actual AST-extracted pure discovery
functions and sanitized live GitHub records. These four definitions are
AST-identical in the workbench and installed engine: `Build`, `find_push_run`,
`find_artifact`, `web_build_for`.

- The installed ship's success count is three after the manual web run.
- `web_build_for` returns `None`: it calls `find_push_run`, which requests and
  accepts only `event=push`, branch `main`, and the requested SHA.
- The unchanged `find_artifact` accepts this exact run's artifact metadata when
  called directly. The event restriction occurs before artifact selection.
- `deploy(..., component="web")` also permits an already stored build for the
  exact requested SHA. Its stored provenance was **not checked** in this review.
  Therefore this finding does not establish that the active staging deploy failed.

Installed engine target:
`/opt/ac-release/releases/2e15c7720c97e43b9f4a3cbb76cdce6a15f0541f/ac_release.py`.
Relevant installed lines: `ac-ship` 144–163; engine `find_push_run` 407,
`web_build_for` 618, `deploy` 4253 and `stored_build` 4293.

| Source                                       | SHA-256 at inspection                                              |
| -------------------------------------------- | ------------------------------------------------------------------ |
| `/usr/local/sbin/ac-ship`                    | `d47de738a4b86082c8ab9d65e6fe7da193caf980a908194871d3f38a9429a2e5` |
| Installed `ac_release.py`                    | `1c028e25d24d97cdb61881a39efe009c493b7ba02c48cc43fed138facf46e677` |
| Workbench `infra/release/ac_release.py`      | `e5fc5e3d078a5d6b54e1c45817e9d34f4ecc26d820fe86b1eff732c986244b96` |
| `.github/workflows/sales-xray-web-image.yml` | `61bbaa7c62e9eac1eea6ff3f576a0d68a1b5eef3e583dbe34c79b16254e01134` |

## Later failure, canary and installed-tool reconciliation

The 23:15 UTC coordinator request records a real failure: the ship log ends at
23:12:11 UTC with `Ship v0.41.0 stopped: staging web deploy failed`. Read-only
systemd inspection confirms that `ac-ship-v0-41-0.service` exited with status 1
at 23:12:12 UTC. A later, separate staging canary started at 23:13:08 UTC and
finished successfully at 23:14:02 UTC. Preserve both results; the canary does
not turn the failed ship execution into a successful one.

The operator's note labelled 23:20 UTC says staging now has the AMR core and
the earlier web, with production still on v0.40.0. Independent HTTP reads through
the local edge on port 8080 confirm the following served identities:

| Environment | Core SHA                                   | Web SHA                                    | Both health responses |
| ----------- | ------------------------------------------ | ------------------------------------------ | --------------------- |
| Staging     | `70000783a9bbe7f9b21523f978f04a7d3084a83e` | `fa846dc1264130e295eccc13daf6164c673c8a8a` | HTTP 200              |
| Production  | `fa846dc1264130e295eccc13daf6164c673c8a8a` | `fa846dc1264130e295eccc13daf6164c673c8a8a` | HTTP 200              |

The installed `ac-ship` changed since the original capture. Its new SHA-256 is
`2e72081e6ffdf5551c3ecd35f6721b293ac7849e7f45d1170991aa13399b9148`.
The installed engine and checked web workflow retain the hashes above. The new
ship error handler skips any web deployment error containing
`no Sales Xray web build`, leaving the currently served web in place. This is an
outer-script change; exact-source dispatch admission remains unresolved. A fresh
pure-function replay still returns `None` from installed `web_build_for` for run
38182582161, while unchanged artifact metadata checks accept artifact 11718458319.
The existing artifact remains successful and unexpired. No second build is needed.

The candidate-specific comparison establishes unchanged web source. The exact
`fa846dc` to `7000078` delta contains only `signals.py` and three Python test files.
All eleven compared web build-input Git objects are identical: the web app and
TypeScript trees, web infrastructure, Docker ignore rules, workflow, package and
pnpm manifests, and the workflow's three artifact-pool helpers. The Dockerfile
copies the web app, TypeScript packages and package manifests; none changed.

This supports retaining the existing verified web source for this exact
native-only candidate, with its actual `fa846dc` identity. It does not establish
identical image bytes: `AC_RELEASE_ID` is a SHA-specific build argument, and the
web image's source marker remains the earlier SHA. The later canary is additional
staging evidence, not an exact-`7000078` web deployment or engine admission.

Source comparison receipt:
`/home/acdev/strikes/1355/web-source-equality-20261011.json`, SHA-256
`2b59625c20684e3d3fc9e5ca94358f32e1f1993d9b27012990a4964197f2d966`.
It retains both commit pins, all four changed paths and both Git object IDs for
every compared input. Reproduce with `git diff --name-status <base> <candidate>`
and `git rev-parse <sha>:<path>` for each listed input; no build is required.

Two source findings remain for the operator:

- The numeric workflow-success count is unchanged. Distinct required workflow
  identities are still needed; missing or undiscoverable web metadata does not
  prove that all web build inputs are unchanged.
- The generic error-message shortcut does not perform this source comparison or
  bind a compatibility receipt to the retained core/web pair. A future changed
  web with an undiscoverable build could take the same shortcut. Either admit
  the existing exact-source artifact through the engine or verify unchanged web
  build inputs for the actual candidate/retained-web pair and preserve both
  identities through promotion and rollback. This one source-equality receipt
  cannot authorize reuse for later candidates.

The operator reports an 8.87 MB logical dump against the 8 MiB bound. That size
was not independently remeasured in this reconciliation. Keep the backup refusal
and the owner's capacity/data decision separate from CI and staging health.
Production promotion is not established.

New read-only receipt:
`/home/acdev/strikes/1355/ship-reconciliation-20261011.json`, SHA-256
`6458602b75ec815e9695ec9e4bac628f12539f1df4ce69473196cd471744f20f`.
Reproducer: `/home/acdev/strikes/1355/reconcile_ship_20261011.py`.
All four inspected source hashes stayed stable during capture. The original
replay receipt and its digest remain unchanged. Public-host reads from this seat
returned HTTP errors; the served identities above come from successful local-edge
reads with the actual host names. The supported release status command was
unavailable to this unprivileged seat because its staging pause file is protected.
Stored exact-SHA provenance, native-transition receipts and artifact payload were
not inspected. No installed tool, release state, data or running service was changed.

## Minimal operator repair

1. Keep the existing ship lock and pinned merge SHA `M`. Replace global
   `gh run list --limit 10` and numeric success counting with separate
   workflow-file queries for `application.yml`, `sales-xray-web-image.yml`,
   and, only for `NATIVE_RELEASE=1`, `sales-xray-native-image.yml`. Filter each
   candidate by exact `M`, repository, workflow path and allowed event; bind
   one run ID and its attempt per required workflow. Handle pagination and API
   errors explicitly. Two successful Application runs cannot substitute for a
   missing native run. Extra successful runs cannot make the loop wait forever.
2. For the web workflow, reuse an existing eligible exact-source run, including
   an active run, rather than dispatching another. Retain the existing bounded
   failure/rerun policy for the bound run. A failed, expired or ambiguous build
   is not a missing run and must produce a specific refusal or recovery path.
3. Only when exact-source web-run absence is established, dispatch the existing
   workflow once with structured body
   `{"ref":"main","inputs":{"frozen_sha":"<M>"}}`. Verify `main` still
   points to `M` before dispatch and require the returned/discovered run's
   `head_sha` to equal `M` afterwards. Persist the dispatch attempt and returned
   run ID in the operator's ship receipt. An ambiguous POST or a moved main
   stops automatic dispatch; it must not trigger a repeated POST.
4. Add a web-only discovery function in the engine, used by `web_build_for`,
   admitting `push` or `workflow_dispatch` only with exact `head_sha=M`,
   `head_branch=main`, repository and web workflow path, completed success,
   and the existing exact-name/run/SHA/digest/expiry/size artifact checks.
   Preserve `find_push_run` and all core/native admission policies. Keep full
   download digest, inventory, source/marker and image verification in the
   existing web store/deploy path. Do not broaden automated train discovery as
   part of this manual ship repair.
5. Require every distinct required workflow to succeed and the exact-source web
   artifact to be admissible before the existing staging phase. Keep the native
   input guard, no-migration native constraint, native preparation, all required
   release CI, backup bound, canaries and promotion sequence intact.

GitHub's current documented dispatch endpoint accepts a branch or tag `ref` and
configured inputs, and returns the workflow run ID and URLs. Do not assume a raw
commit is a documented dispatch ref. The exact checkout comes from this
workflow's `frozen_sha` checks. See
[workflow dispatch](https://docs.github.com/en/rest/actions/workflows#create-a-workflow-dispatch-event)
and [workflow-specific run queries](https://docs.github.com/en/rest/actions/workflow-runs#list-workflow-runs-for-a-workflow).

The comparison above supports source retention for this one native-only pair;
a generic unchanged-web shortcut is not proven under this installed contract.
`deploy web M` looks up a build for `M`, and the verifier requires the web source
and release marker to equal that SHA. No general cross-SHA web-input compatibility
proof was found. Reducing the required count to omit web would therefore be
insufficient. A future reuse mode would need an explicit digest-bound core/web
pair, complete build-input comparison and acceptance through the existing engine
contract; retain both real source SHAs and the immutable staging/production pair.

## Required operator acceptance

| Case                                                       | Required result                                                             |
| ---------------------------------------------------------- | --------------------------------------------------------------------------- |
| Native-only delta, no web run                              | One exact-source dispatch; one retained run ID; web admitted before staging |
| Existing active or successful exact-source web run         | Zero new dispatches; wait for or verify that run                            |
| Duplicate Application successes, missing native            | Remains incomplete; two Application runs never count as native              |
| Extra successes or more than ten unrelated main runs       | Required workflow identities still decide readiness                         |
| Wrong SHA, branch, repository, path or event               | Refuse                                                                      |
| Expired/missing artifact or wrong run/digest/source marker | Refuse before deployment                                                    |
| Main advances during dispatch or POST result is uncertain  | Stop automatic dispatch and reconcile the recorded attempt                  |
| Native delta plus migration delta                          | Existing native guard still refuses                                         |
| Production logical backup exceeds its bound                | Existing backup guard still blocks promotion                                |

The coordinator's existing run is already successful; do not dispatch another
build or start another ship. The separate foundation backup-bound decision
remains operator-owned. This review changes no root tool, engine, workflow,
runtime, data, dependencies or required CI.

Local reproducible replay:
`/home/acdev/strikes/1355/replay_ship_workflow_20261011.py`.
Receipt: `/home/acdev/strikes/1355/ship-workflow-replay-20261011.json`, SHA-256
`6b19a683e9029d573bb3631bec7e40e4587a82801a8881b6e62596d90ebc0d33`.
This proves discovery behavior and metadata identity; the image payload was not
downloaded or independently verified, and no deployed acceptance is claimed.
