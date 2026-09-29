# AUT-176: OS baseline records libssh-4's security update

Date: 29 Sep 2026.

## What happened

- Since 13:44 IST staging refused main (5417c694). The installed foundation's backup tools don't know
  migration `20260929_0052`, and installing the foundation from main needs the #98 baseline
  (`ubuntu-noble-amd64-2026-09-28-v1`, ffmpeg) first.
- At about 14:55 IST the reviewed `bootstrap-host.sh baseline` phase ran from main's exact commit. It installed
  ffmpeg and its dependencies. Its exact-graph check then failed on one line:
  `libssh-4:amd64 0.10.6-2ubuntu0.5` live against `0.10.6-2ubuntu0.4` in the manifest. The installer removed the
  active marker and wrote recovery evidence. Services were unaffected.
- `libssh-4` is in the original 30 Aug baseline. The phase unholds managed packages, and apt moved it to the
  Ubuntu security update. `0.10.6-2ubuntu0.4` is no longer in the archive (`apt-get install libssh-4=…0.4`:
  "Version … was not found"), so neither the old nor the 28 Sep baseline can be restored.

## Change

- New baseline `ubuntu-noble-amd64-2026-09-29-v1`: the 28 Sep resolved list with `libssh-4:amd64` at
  `0.10.6-2ubuntu0.5`.
- New resolved list SHA-256: `389c187588bb1c0216c5d5b433be480236849192c26b7b299d48328f43a085dd`. This equals
  `AC_OS_BASELINE_LIVE_GRAPH_SHA256` in the host's recovery evidence. On ac, `dpkg-query -W
  -f='${binary:Package}\t${Version}\n' | LC_ALL=C sort` differs from the 28 Sep list in that one line only.
- The policy test now builds the expected list as: the frozen 30 Aug list, plus the 28 Sep ffmpeg set, plus
  `ubuntu-noble-amd64-2026-09-29-v1-updates.tsv`. That last file holds one version replacement; an update may
  replace a listed package's version, never add a package.

## Verification

- `bash tests/infra/test-os-baseline-policy.sh`: passed.
- `bash tests/infra/test-os-baseline-transaction.sh`: passed.

## After merge

On ac, run the baseline phase and then the immutable foundation release from the merge commit
(OPERATIONS.md). Then resume staging.

## Follow-up

The baseline installer pins only top-level packages, so a dependency's security update breaks the exact graph
whenever a baseline phase runs. Track separately: pin every resolved package, or refresh the manifest in CI.
