# AUT-2188 — CI prerequisite mirror resilience

Source baseline: `5869a25ff2d0dc49b3788799308b52a356b43845`. Workbench implementation; no deployment or host/package changes performed.

## Change

Release validation and workbench Python, e2e and visual jobs use one pinned composite action. Its exact cache key includes the requested package list from the frozen Playwright runtime, runner image version, OS/architecture, dependency lockfiles and installer source. The cache contains the complete apt download transaction (including transitive dependencies/upgrades), an archive SHA-256 manifest, and locked browser files. A cache hit verifies that manifest, installs local Debian files with `--no-download --no-remove`, skips browser downloads, and still proves ffmpeg/ffprobe, filesystem commands and a real locked Chromium launch. Missing or damaged cache content fails closed without mirror fallback.

A cache miss retains bounded apt update/download and browser download attempts. The cache is saved immediately after successful prerequisite proofs, so downstream test failures do not discard a valid cache. Cold caches, cache eviction, runner image updates and changed lockfiles can still require the mirror; this change removes that dependency from warm runs.

Workbench prerequisite and Node installs run in the foreground. Previously `bash -e` could exit a background subshell before it wrote `prereq.rc` or `pnpm.rc`; the wait then reported a timeout instead of the actual failure. Required checks and shard coverage are retained.

## Verification

- Focused prerequisite, registration workflow and recovery workflow checks: **74 passed** (14.05 s).
- Ruff formatting and lint: pass for all touched Python files.
- Required `uv run python -c "import ac_platform.http"`: pass.
- Real apt acquisition fixture: two fictional Debian packages with a dependency, empty package indexes/status and no configured sources. The real install path rejects the wrong archive directory and passes the cached archives to a recording dpkg stub when the directory matches. The stub prevents host package changes and post-install hooks. Solver simulation/download-only had hidden this distinction; both are insufficient evidence for offline installation.
- Fake-host tests prove complete cold transaction capture, warm install/probes without update or downloads, image/runtime/component key isolation, preinstalled packages, and rejection of altered/missing/extra archives, mismatched package lists and missing manifest.
- Shared-action guards cover exact cache restore/save, early save, foreground dependency status, mandatory proofs and retained shard evidence.

## Hosted validation and release follow-up

- Implementation: `20377e2e`; workbench historical-source overlay/routing: `533e6019`.
- [Hosted check 39774635110](https://github.com/authorityclosers/authority-closers-platform/actions/runs/39774635110): cancelled after the compatibility follow-up superseded its source; no success claim.
- [Hosted check 39775449427](https://github.com/authorityclosers/authority-closers-platform/actions/runs/39775449427): lint passed; Node visual prerequisite cold download succeeded, but offline install failed because it did not name the download archive directory. Corrective change sets the same directory for both download and install and explicitly retains downloaded packages. The strengthened real apt regression reproduces this exact failure and passes with the corrected arguments.
- Source tool `scripts/ci/wb-ci` now overlays the shared action and helper with the current workflow for pinned historical checks. The authorized operator must refresh the installed `/usr/local/bin/wb-ci` copy from the reviewed source.

Corrected-source hosted validation is pending. This result is not a release or a week-long stability claim.

Acceptance requires the authorized release operator to include the reviewed commit, then seven days of release and workbench runs without prerequisite/apt failures. Record cache hits/misses and distinguish actual dependency failures from missing background status files. Do not close the parent issue before that observation is complete.

## References

- [GitHub dependency cache scope and matching](https://docs.github.com/en/actions/reference/workflows-and-actions/dependency-caching)
- [Separate cache restore/save actions](https://github.com/actions/cache)
- [apt-get download-only and no-download options](https://manpages.ubuntu.com/manpages/noble/en/man8/apt-get.8.html)
