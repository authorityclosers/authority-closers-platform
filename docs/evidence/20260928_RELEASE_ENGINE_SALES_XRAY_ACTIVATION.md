# Release engine: Sales Xray activation per release (#80)

28 Sep 2026. Automates the step that kept automatic staging paused: every core
release that runs hosted Sales Xray needs
`/etc/authority-closers/sales-xray/<env>/activation-<sha>.json`.

## Why (the manual record this replaces)

On 28 Sep, staging was moved to `main` 40e0bc53 (PR #79) by hand. It took these
steps:

1. Load the native build 390b4285 (verify, extract the helper, `docker load`).
   The earlier native build (94b47e41) could no longer be reused, because T3
   changed `.github/workflows/sales-xray-native-image.yml`, which is a pinned
   native input.
2. Fetch the GitHub artifact and run records, then write the native reuse proof.
3. Write a renewed approval (owner decision: ₹10,000 cap, 90 days to
   2026-12-27, keep-for-training retention, three named internal testers,
   same providers and models), canonicalised with the hosted contract.
4. Run `prepare-sales-xray-native-activation.py` and publish the descriptor.
5. Render and install the staging native units for the new image. This needed
   `releases/390b4285/` (unpacked by an earlier attempt) and an explicit
   `--renderer`.
6. Deploy through the engine. The Sales Xray worker then crash-looped
   (`hosted_reporting_launcher_scope_mismatch`): the approval no longer named
   OpenAI, whose only grant was an expired one-source benchmark, but the
   service still configured it. The activation was re-prepared from the last
   non-OpenAI source activation (1ee6a6d8). The never-started worker container
   (12 start failures, 0 jobs) was removed, and the release was re-applied.
7. The engine's check had passed with the worker crash-looping. Its store prune
   had also deleted the kept native zip, and GitHub keeps native artifacts for
   one day (390b4285 expired 2026-09-29 07:15 UTC).

Staging has run 40e0bc53 since, with all 8 containers up and the worker steady.

## Change

`infra/release/ac_release.py`:

- **Activation carried forward.** For each core deploy (real and dry run), the
  engine calls `prepare_activation`. If the running release has an activation
  and the target has none, it runs the repository prepare tool:
  - the **approval is carried forward unchanged** (no `--approval-file`);
  - the native image stays the one already running;
  - the native reuse proof is built from `release-store/native/<sha>/` and the
    engine's git mirror.

  A real deploy seals and publishes the descriptor and its digest (mode 0444).
  A dry run prepares inside its stage and publishes nothing.
- **Refusals with a clear message.** The engine refuses if the approval or its
  acquisition policy lapses within a day, or if the release changes the native
  image inputs.
- **Permanent native store.** `release-store/native/<sha>/` keeps the build zip,
  the artifact record and the run record. The per-commit store prune never
  touches it. Each core deploy stores its commit's own native build if CI made
  one. The new `ac-release store-native SHA [--from ZIP]` adopts a saved copy
  only when it matches GitHub's recorded digest and size.
- **Worker check.** When the release has an activation, the core check waits
  for `sales-xray-worker` on the release API image, then requires it to stay
  up for 30 s without a restart.
- **Approval end date in status.** `status` shows when each environment's Sales
  Xray approval ends, with the days left.

The engine never creates, renews or widens an approval.

## Verification

- `tests/infra/test_ac_release.py`: 60 passed on Linux (WSL, Python 3.12), 11 of
  them new. They cover:
  - carry-forward, reuse-proof contents and publish permissions;
  - dry runs publishing nothing;
  - no hosted activation, an expiring approval, changed native inputs and a
    missing native load;
  - download-once, digest-checked adoption and the expired-without-copy message;
  - the store prune leaving the native store alone;
  - the restart check;
  - the status output.
- `ruff check` and `ruff format --check` pass on both files.
- **Real tool on the server (dry run, nothing published).** The branch engine
  prepared an activation for `main` commit 362ec2a9 from staging's live
  40e0bc53 activation. The repository prepare tool and native verifier
  accepted the engine-built reuse proof for native 390b4285, and five
  activation files were produced in the stage.
- The same run stored native 390b4285 permanently in
  `release-store/native/390b428568b443ae6b748ccb11e7789574c8c926/` before
  GitHub's expiry.

## Still manual (follow-up tasks)

- Installing a **new** native image: loading it, then rendering and installing
  the units. `install-sales-xray-native.py` expects
  `releases/<native-sha>/scripts` for its renderer and defaults `--renderer` to
  a legacy release.
- Changing an approval (limits, testers, providers). This belongs in Admin
  (Task E).
- The installer holds a release for recovery when the hosted worker never
  started (exit ≠ 0, zero jobs).
