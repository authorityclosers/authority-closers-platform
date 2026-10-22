# AUT-2188 — CI prerequisite mirror resilience

Latest status (22 Oct, 18:09 UTC wake): later v0.84/workbench failures supersede the earlier warm-run checkpoint as reliability evidence. The verified prerequisite-bundle correction and seven-day acceptance remain open. The storage follow-up below implements one-day workbench retention and summary-only green shard uploads.

Source baseline: `5869a25ff2d0dc49b3788799308b52a356b43845`. Workbench implementation; no deployment or host/package changes performed.

Latest validation: **full current-source CI is green** on workbench `4643dd63`, [run 39781371721 attempt 2](https://github.com/authorityclosers/authority-closers-platform/actions/runs/39781371721/attempts/2). Exact Node cache reuse is proved by [attempt 3](https://github.com/authorityclosers/authority-closers-platform/actions/runs/39781371721/attempts/3). Release inclusion and the seven-day observation remain open.

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

- [Corrected-source hosted run 39776626824, attempt 1](https://github.com/authorityclosers/authority-closers-platform/actions/runs/39776626824/attempts/1): **SUCCESS** on `2a90f2cc5e90b42a77ab87c340a83d4ebb048d41`. Plan, lint, Python, visual and summary passed; 74 tests passed in 10.03 s. Python cold update/download/offline install took 8/4/9 s. Node cold download timed out once at 300 s, then succeeded in 227 s; offline install and Chromium proof passed and its cache was saved before screenshots. Total 10m51s.
- [Same-source reuse run, attempt 2](https://github.com/authorityclosers/authority-closers-platform/actions/runs/39776626824/attempts/2): Python restored the exact cache, verified **96 Debian archives**, installed with downloads disabled, proved ffmpeg/ffprobe/Chromium, and passed **all 74 tests** in 9.64 s. Its log contains no apt update/download or Playwright install. The overall rerun was later cancelled when another workbench request reused the CI slot; this is not a green workflow claim.
- Attempt 2's Node visual job passed, but correctly missed its cache because its runner image was `20261012.334.1`, versus `20261018.339.1` on attempt 1. Both image-specific Node caches were saved. This confirms image isolation, not Node warm reuse.
- Exact Node warm replay remains for validation after review. Its shared slot was occupied by another live e2e run; the pending lock wait was stopped without starting another rerun or altering that run.

Implementation is ready for CTO source review. No release or week-long stability result is claimed.

Acceptance requires the authorized release operator to include the reviewed commit, then seven days of release and workbench runs without prerequisite/apt failures. Record cache hits/misses and distinguish actual dependency failures from missing background status files. Do not close the parent issue before that observation is complete.

## References

- [GitHub dependency cache scope and matching](https://docs.github.com/en/actions/reference/workflows-and-actions/dependency-caching)
- [Separate cache restore/save actions](https://github.com/actions/cache)
- [apt-get download-only and no-download options](https://manpages.ubuntu.com/manpages/noble/en/man8/apt-get.8.html)

## P0 cold-cache report reconciled (22 Oct 2026)

[Failed full run 39777392383](https://github.com/authorityclosers/authority-closers-platform/actions/runs/39777392383) tested request `4e63c0221b77b602621cc647db24b83041615836`. Its hosted helper predates correction `2a90f2cc`: the offline install omitted the download archive directory. Python job `119819799635` and Node visual job `119819799306` both reported a cache miss, completed bounded apt update/download, then failed the local install. This was the previously corrected archive-directory defect, rather than a policy that rejects cache misses. The action passes `--offline` only on an exact hit; misses use bounded package and browser downloads.

The current workbench pin `4643dd63139ffb229872e91d75131cf5a10b97db` includes the correction. Its prerequisite helper/action, workflows, tool and owned tests are unchanged from `2a90f2cc`. The isolated real-apt regression was reproduced on 22 Oct at 12:43 UTC: **1 passed in 0.30 s**, without host package changes or network access.

[Full cache-warming validation 39780623950](https://github.com/authorityclosers/authority-closers-platform/actions/runs/39780623950) runs this current workbench pin with all Python shards, web, visual and release browser proofs (`--full --e2e`). It was launched through the committed source tool to include the corrected action/helper overlay. Request `9aedaffd`, kept branch `wb-ci/slot-1`; hosted helper bytes match the workbench source exactly. Initial state at 12:44 UTC: queued. The run result and actual cache hits must be recorded before claiming validation or successful warming.

The first request's plan selected **only e2e**, because the existing planner treats explicit families as a replacement even under `--full`. It was cancelled without claiming full validation. This separate planner defect is recorded in [AUT-2189](/AUT/issues/AUT-2189); no planner source change is included here.

The replacement [full cache-warming run 39781371721](https://github.com/authorityclosers/authority-closers-platform/actions/runs/39781371721) explicitly requests `--full --web --py --visual --e2e` for the same source `4643dd63`. Request `a4267b1a`, kept `wb-ci/slot-3`. This is the full validation request; the earlier run is superseded.

Current-head cold fallback is proved by completed jobs in the replacement run:

- Node visual job `119833304779`: **SUCCESS**, runner image `20261021.345.10`, exact cache miss `ci-prerequisites-v1-e2642c3984162c140e9d56a2d81bfb2a7b96eb4daa52b171a94f839cea71d426`. Bounded update/download/local install took 5/3/6 s; browser install took 7 s; Chromium `145.0.7632.6` launched. Cache saved at 12:49:22 UTC before screenshots.
- Python b2 job `119833305163`: **SUCCESS**, runner image `20261012.334.1`, exact cache miss `ci-prerequisites-v1-0bc927277c4ad2e5159b5c0cb1dc59d49ac2f04822e03e3f3582c654ca0f388b`. Bounded update/download/local install took 8/5/7 s; cache saved at 12:49:08 UTC; **779 passed, 1 skipped** in 118.25 s.
- The replacement request tree differs from `4643dd63` only at `.wb-ci/request.json`, confirming source matching without overlays or uncommitted product changes. Other jobs were still running when these cold proofs were recorded.

[Root handoff AUT-2190](/AUT/issues/AUT-2190) owns the installed launcher refresh, with exact source `scripts/ci/wb-ci` at `533e6019`, single-file serialized install, byte/mode/overlay verification and guarded rollback. Platform has made no host changes.

Replacement attempt 1 finished **FAILURE** after 14m39s: lint, web, visual, e2e and **12 Python shards passed**; five Python shards exhausted the bounded cold apt download attempts. Example job `119833305152` (b3) missed the same image/key that successful b0/b2 had already populated; update took 22 s, download attempts timed out after 300/300/77 s. Their valid cache was published after the stalled shards' initial restore. This records the remaining first-fill mirror exposure rather than hiding it.

[Same-source warm replay, attempt 2](https://github.com/authorityclosers/authority-closers-platform/actions/runs/39781371721/attempts/2) was started after attempt 1 completed, under the same slot-3 lock. The branch still matched request `a4267b1a` before rerunning. All families, source and branch are retained. Result and exact Node warm proof are pending.

## Full current-source verdict

[Run 39781371721, attempt 2](https://github.com/authorityclosers/authority-closers-platform/actions/runs/39781371721/attempts/2): **SUCCESS** for workbench `4643dd63139ffb229872e91d75131cf5a10b97db`, request `a4267b1a6a387e0cff6942ae34ec18012258cbac`. All 17 Python shards, full lint/type checks, web tests, visual, e2e and the summary passed. Summary job `119843928071` verified **91 family-a files and 887 family-b files**, selecting attempt-2 evidence for every shard. This is a full workbench-source verdict, without claiming a release/PR or production verdict.

Attempt-2 b12 job `119840456875`, previously a cold timeout, restored exact cache `0bc92727` on image `20261012.334.1`, verified **87 Debian archives**, installed offline in 12 s and passed **808 tests** in 138.91 s. No apt update/download occurred. Node visual also passed; its move to image `20261012.334.1` correctly filled separate key `ccd1307e` (6/1/5 s update/download/local install and 6 s browser install).

A Node-only replay was triggered after the green full run, retaining the same locked branch and source, to obtain the outstanding exact Node hit.

## Exact Node warm proof and launcher handoff

[Attempt 3](https://github.com/authorityclosers/authority-closers-platform/actions/runs/39781371721/attempts/3), Node visual job `119844385359`: **SUCCESS**. Runner image `20261012.334.1` restored exact key `ci-prerequisites-v1-ccd1307ec2c02083412c6e291c76bbf4272d1b69ac1eb5de0c1cd0899f53a8d8`; `PREREQ_CACHE_HIT: true`. It verified **9 Debian archives**, installed offline in 8 s and launched Chromium `145.0.7632.6`. Its completed log contains **no apt update, apt download or Playwright install**. This closes the prior Node warm-reuse evidence gap. The temporary log reader used the wrong CLI JSON field after the watch; a read-only collection with the supported `attempt` field confirmed the actual green result and all four proof conditions. No extra workflow rerun was needed.

Root's full installed/source comparison found that the committed launcher omitted the installed core-API headroom guard and used a 3-second watch. The source now preserves **below 400 core requests → exit 75** and **30-second watches**, while retaining both prerequisite action/helper overlays. This launcher-only follow-up occurs after the source-matched full run above; it does not change its tested application, workflow or prerequisite helper bytes.

The reconciled launcher SHA-256 is `b591a73118ba3c7bdc5964b7e63db51bd6447f30d59fc74109ae3fc00a29aff2`, blob `e5052f75f94947a174581159791d39c778e9a48d`. **12 bounded local checks passed**: Bash syntax, absolute-path help without dispatch, parsed overlay paths, fictional remaining counts 0/399 → 75 and 400/5000/unavailable → 0, guard ordering before slots/push, watch interval, candidate hash and an installed comparison showing only the two overlay additions plus trailing whitespace. These checks made no network, host, branch or slot changes.

[Root handoff AUT-2190](/AUT/issues/AUT-2190) remains the single installer. Its prior source-pin blocker is addressed by the reconciled commit; install approval still belongs to the existing review path. No installation, release or production change is claimed. The parent remains open for authorized release inclusion and seven days of release/workbench observation.

## Workbench artifact storage follow-up (22 Oct 2026)

Source baseline: `62be474e43b9a54dd76e42e105ea0def3e475ca2`. Implements the orchestrator's 18:09 UTC request after the reported v0.85 schema-publication storage failure. This is an artifact-growth change; it does not satisfy the outstanding prerequisite reliability acceptance.

- All four workbench upload steps explicitly use `retention-days: 1`: green coverage summaries, failed/cancelled shard diagnostics, `wb-screens`, and `wb-e2e-*` reports. Future uploads receive this lifetime.
- Green non-targeted Python shards upload only `manifest.json`, with missing summaries treated as an error. Successful targeted runs need no shard artifact. JUnit and the full shard directory upload only on failure/cancellation.
- Artifact names, SHA/attempt identity, collection patterns and the final complete-coverage check are preserved. The manifest is required by that check, so retaining only this coverage summary avoids weakening test coverage.
- Release and schema artifact policies are outside this diff. No artifact deletion, settings change, deployment or installed-tool change was performed.

Verification: **5 focused tests passed in 0.30 s**. The policy checks cover every workbench upload, one-day expiry, green/failure payloads, preserved collector identity and missing-manifest failure. A fictional two-shard fixture uploads only manifests, excludes adjacent JUnit diagnostics, and passes the real complete-coverage verifier. The existing release-retention policy regression also passes. Ruff formatting/lint, YAML parsing, diff whitespace and the required `import ac_platform.http` pass. No new hosted full-run verdict is claimed for this workflow-only follow-up; the prerequisite-bundle correction requires its own cold/offline full/e2e proof.

## Verified producer and offline consumers — implementation checkpoint

The replacement uses a producer job before release/workbench matrix consumers. It obtains the complete declared Debian dependency closure using empty dpkg status and isolated, GPG-authenticated HTTPS `archive.ubuntu.com` / `security.ubuntu.com` indexes. It builds a local package repository, proves an empty-state offline solve and an actual compatible-runner installation, and proves both frozen Python and Node Chromium runtimes before publishing.

Consumers receive a concrete GitHub artifact ID/digest, producer run/source, repository and locked-input identity. They verify the exact artifact/payload digests, safe archive paths, complete package-file hashes, Ubuntu24.04/amd64 policy and a real offline package solve before installation. They retain codec/filesystem and actual locked-browser launch proofs. Consumer sources are file-only; consumer package/browser downloads have no fallback. Both producer and consumer actions blackhole the failing Azure mirror on their disposable GitHub runner; no cache restore is used.

A fresh, successful main producer with matching locked identity may be reused across sibling branches through its immutable artifact reference. Missing/expired/unavailable publication is rebuilt only in the bounded producer. Corruption and authentication failures fail closed. A baseline that no longer solves triggers a fresh producer build. Image version is retained in provenance; compatibility is checked by the complete local repository and solver rather than by a partial producer transaction. Bundle artifacts have a separate **two-day** lifetime, a 36-hour reuse age limit and a two-hour remaining-expiry margin. One-day diagnostic retention is preserved.

Focused verification: **109 tests passed in 14.08 s**, including the prerequisite helper/workflow contracts, registration/recovery gates, bundle cold/warm/recovery/corruption/baseline cases and diagnostic-retention policy. The real isolated apt fixture acquires both fictional dependency archives through the local repository with downloads disabled and a recording dpkg stub; host status remains empty and no maintainer hooks run. Omitting the dependency fails the real solver. Ruff, targeted YAML formatting, required API import and Bash syntax pass.

This is an implementation checkpoint pending a fresh source-matched hosted producer/full/e2e verdict and sensitive workflow review. Earlier warming runs are not reused as acceptance. No installed launcher, production image, deployment, real data or secret was changed.

## Fresh cold full/e2e proof — 22 Oct 2026

Implementation commit: `c2ade062061f09ffdd4c7269d8d5858072000e2a`. [Fresh run 39837257389, attempt 1](https://github.com/authorityclosers/authority-closers-platform/actions/runs/39837257389/attempts/1) is **SUCCESS**, completing in 9m37s from push. Request `adfc31e64dd539f37f4a4af507b433e00ad82cc1` differs from that source only at `.wb-ci/request.json`; all families were explicitly selected. No prerequisite cache restore or historical warming replay was used.

- Producer job `120028796583` passed in 172s with the Azure mirror blackholed. Authenticated non-Azure indexes completed in 6s, the complete empty-status Debian closure downloaded in 29s, and the offline runner install completed in 12s, all on first attempts. Both frozen Chromium runtimes launched (`145.0.7632.6`).
- [Published artifact 12452071131](https://github.com/authorityclosers/authority-closers-platform/actions/runs/39837257389/artifacts/12452071131): **452,074,312 bytes**, ZIP SHA-256 `8f1e02fa0191f5e0e718e0ba88eda11959baf1a88fdb2d70ffbe38e0d43f463c`, locked-input identity `f2f6966933d5e6ec94e1a7feeb383042af56a49258bc6f1c23887ccb04b8e38c`. GitHub metadata binds it to producer run/source above; created `2026-10-22T19:09:58Z`, expires `2026-10-24T19:09:55Z`.
- All **19 matrix consumers** (17 Python shards, visual and e2e) logged a successful complete local dependency solve and `consumer apt/browser downloads: 0`. Each blocked Azure before installation; none ran the producer's remote-index/download path. The three browser-bearing Python shards and both Node jobs launched Chromium from the verified bundle. Codec/filesystem proofs passed where required.
- Lint/type checks, web, visual and e2e passed. Summary job `120033121797` verified attempt-1 manifests for all 3 family-a and 14 family-b shards: **91 + 898 = 989 test files**. The green uploads contain coverage summaries, preserving the reviewed one-day diagnostics policy. E2e's final browser suite reported 3 passed.
- GitHub's job metadata for b13 (`120030256765`) still reported `in_progress` after the run concluded successfully. Its complete log records **825 passed, 3 skipped**, successful manifest upload and cleanup; the green summary selected its attempt-1 manifest. This API inconsistency does not substitute for the recorded test/coverage evidence.

The local focused cold/warm/corrupt/incompatible/recovery tests and this cold hosted run are ready for SHA-bound CTO source review. Hosted reuse of a successful **main** publication, the integrated release workflow, sensitive release approval, production version and seven days without prerequisite failures remain open. The two-day prerequisite bundle is separate from one-day disposable diagnostics; future retention does not reclaim existing storage. No release, deployment, artifact deletion or installed-tool refresh is claimed.
