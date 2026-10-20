# Workbench CI: tests and screenshots run on GitHub, not on ac

Owner order, 20 Oct 2026:
- Heavy checks (tsc, eslint, vitest, pytest, Playwright) must not run on the ac VPS. It has 4 cores and serves dev
  live; parallel build chats pushed its load to 14 and dev requests took 20–57 s.
- The repository is public, so GitHub-hosted runners are free. Split the work so a full run finishes in under 5 minutes.

## Use it

On ac as any user (it re-runs itself as `acdev`), or from the laptop with `ssh ac wb-ci ...`:

```bash
wb-ci                                   # default: only the jobs the HEAD commit's paths touch, scoped to its files
wb-ci --changed <base>                  # the same for everything in <base>..HEAD
wb-ci --full                            # every job: lint + tsc, vitest, screenshots, 17 Python shards (< 5 min)
wb-ci --web                             # force the web jobs (scoped to the changed files unless --full)
wb-ci --py-tests tests/core/test_x.py   # one pytest target with PostgreSQL instead of the 17 shards
wb-ci --visual /review-fixture/shell "/?new=1&sx-fixture=auth.email"
wb-ci --include apps/sales-xray-web/app/x.tsx   # also test this uncommitted file
wb-ci --sha 1a2b3c4d --full             # a specific workbench commit
```

**What runs.** Changed paths pick the jobs:

| paths | jobs |
|---|---|
| `apps/`, `packages/typescript/` | lint (prettier + eslint on the changed files), tsc (affected packages), vitest (`vitest related`) |
| `apps/sales-xray-web/`, `packages/typescript/ui/`, `packages/typescript/sales-xray-review-ui/` | the above, plus screenshots of the frames those paths affect |
| `packages/python/`, `tests/`, `alembic`, `migrations/`, `scripts/*.py` | lint (ruff on the changed files, plus mypy) and all 17 Python shards |
| workflow, `scripts/ci/wb*`, lockfiles, `package.json`, `pyproject.toml`, `tsconfig*` | everything, as `--full` |
| docs only | nothing: the summary says so |

`--web`, `--py` and `--visual` force those families.

**What it prints:**
- the run URL;
- each job's result and seconds, with the failed steps;
- links to the screenshots (`wb-screens`: PNGs plus `receipt.json`);
- the number of Python shard reports.

Exit code 0 only when everything passed. Every job writes its own check table (command, pass/fail, seconds) to the run
summary.

## Rules for every chat and agent

- **No heavy checks on ac.** Use `wb-ci`. A single quick test on ac is still fine under `nice -n 19 ionice -c3`, one at
  a time.
- Commit with `wb-commit` first, or pass `--include` for files you have not committed yet.
- Screenshots on GitHub use fictional fixtures only (no API, no real data). Anything that needs dev-live data still
  uses the dev box, briefly.

## How it works

**The helper.** `wb-ci` lives at `/usr/local/bin/wb-ci`; its source is `scripts/ci/wb-ci`.
- It keeps a bare repo, `/home/acdev/src/wb-ci.git`, that borrows the workbench's git objects.
- It builds a request commit: the tested tree, any `--include` files, the current CI files and `.wb-ci/request.json`.
- It pushes that commit to `refs/heads/wb-ci/slot-<n>`, waits with `gh run watch`, prints the summary, then deletes the
  branch.
- One `wb-ci` holds a slot at a time (`flock`, six slots), so runs never cancel each other. Actions caches are scoped
  to the branch name, so a fixed slot keeps its ESLint and Playwright caches warm.
- `--no-wait` uses a unique branch instead.
- The shared checkout's files, index and branch are never touched.
- It also force-updates `wb-ci-base` to the tested workbench commit, so later pushes only send new objects.

**The workflow.** `.github/workflows/workbench-checks.yml` runs only on `wb-ci/**` pushes.

- **plan** reads the request.
- **Full layout: 20 jobs**, the GitHub Free concurrency limit:
  - lint: prettier, eslint, ruff, mypy, and tsc in a full run;
  - vitest;
  - visual: 390 and 1440 px, light and dark, two pages at a time;
  - 17 Python shards.
- **A `--changed` run** gives tsc its own job.
- **The Python shards come in two families that partition the tests:**
  - **a:** about 90 files that mention Playwright, ffmpeg, a codec or the native build. Their shards install those
    prerequisites in the background, about 60 s.
  - **b:** everything else. It installs only the codec (ffmpeg), which database tests need when they upload audio; no browser.
  - Each family is sharded and verified by `python_test_shard.py` with its own exclusion list: the base exclusions
    plus the other family's files.
  - Shards balance by `scripts/ci/wb-python-durations.json`, measured on GitHub runners.
  - PostgreSQL containers and `pnpm install` start in the background while uv installs.
- **summary** downloads every shard's manifest. It runs `python_test_shard.py verify` per family (every file in
  exactly one shard, every shard reported) and fails on any failed job.
- **No `PG*` variables in the jobs.** The local sandbox guard in `development/seed.py` refuses to run when one is set.

**Refreshing the shard durations.** Do this after test files are added or grow:
1. Run `wb-ci --refresh-durations <run-id>,<run-id>,...` with two or three recent full runs. Each file's cost is its
   mean over those runs, which damps the runner-to-runner noise; one run alone balances to noise.
2. Commit with `wb-commit -- scripts/ci/wb-python-durations.json`.

**Safety:**
- No other workflow runs for `wb-ci/**` or `wb-ci-base`: every other `push` trigger is limited to `main`, and nothing
  opens a pull request. Release, image, single-track, migration-schema-publish and the lane gate are unaffected.
- No secrets are used.
- GitHub push protection (secret scanning) checks every push. Never commit secrets to the workbench.

