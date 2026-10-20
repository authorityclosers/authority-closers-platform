# Workbench CI: tests and screenshots run on GitHub, not on ac

Owner order, 20 Oct 2026: heavy checks (tsc, eslint, vitest, pytest, Playwright) must not run on the ac VPS. It has
4 cores and serves dev live, and parallel build chats pushed its load to 14 with 20–57 s dev requests. The repository
is public, so GitHub-hosted runners cost nothing.

## Use it

On ac, as any user (it re-runs itself as `acdev`), or from the laptop with `ssh ac wb-ci ...`:

```bash
wb-ci                                   # web + python + screenshots on the workbench HEAD
wb-ci --web --changed                   # prettier/eslint/vitest on files the HEAD commit changed, tsc of their packages
wb-ci --py --py-tests tests/core/test_x.py   # one pytest target with PostgreSQL, instead of the 4 shards
wb-ci --visual /review-fixture/shell "/?new=1&sx-fixture=auth.email"
wb-ci --sha 1a2b3c4d --web --py         # a specific workbench commit
wb-ci --web --include apps/sales-xray-web/app/x.tsx   # also test this uncommitted file
```

| option | what it does |
|---|---|
| `--sha <sha>` | workbench commit to test (default: HEAD of `dev/live`) |
| `--web` | prettier, eslint, `tsc --noEmit`, vitest (as Application validation's frontend job) |
| `--py` | ruff format, ruff check, mypy, then pytest with the PostgreSQL suites in 4 parallel shards (as Application validation) |
| `--py-tests <paths>` | one pytest job for these paths instead of the shards |
| `--visual [routes]` | screenshots at 390 and 1440 px, light and dark, fictional fixture data, no API; default routes are every review fixture of the Sales Xray visual advisory |
| `--changed [<base>]` | scope prettier, eslint, vitest (`vitest related`) and ruff to files changed in `<base>..<sha>` (default: the commit itself); tsc and mypy still check whole packages |
| `--include <paths>` | add these uncommitted workbench files to the tested tree (read only) |
| `--no-wait`, `--keep` | return after the run starts; keep the `wb-ci/*` branch |

No `--web`/`--py`/`--visual` means all three. It prints the run URL, then each job's result and duration, the failed
steps, and artifact links (JUnit reports, screenshots with `receipt.json`). Exit code 0 only when everything passed.
Each check's own table (pass/fail and seconds per command) is in the run summary on GitHub.

## Rules for every chat and agent

- **No heavy checks on ac.** Use `wb-ci`. A quick single test (`pytest -k one_test`, one `vitest` file) is fine on ac
  only under `nice -n 19 ionice -c3`, one at a time.
- Commit with `wb-commit` first, or pass `--include` for files you have not committed yet.
- Screenshots on GitHub use fictional fixtures only (no API, no real data). Checks that need dev-live data still use
  the dev box, briefly.

## How it works

- `wb-ci` (`/usr/local/bin/wb-ci`, source `scripts/ci/wb-ci`) keeps a bare repo, `/home/acdev/src/wb-ci.git`, that
  borrows the workbench's git objects. It builds a request commit there:
  - the tested tree;
  - plus any `--include` files;
  - plus the current CI files;
  - plus `.wb-ci/request.json`.
- It pushes that commit to `refs/heads/wb-ci/<sha8>-<random>` and waits with `gh run watch`. Afterwards it prints the
  summary and deletes the branch.
- The shared checkout's files, index and branch are never touched. The git guard is not involved: the push happens
  from the bare repo.
- It also force-updates `wb-ci-base` to the tested workbench commit, so the next push only sends new objects.
  `wb-ci-base` triggers no workflow.
- `.github/workflows/workbench-checks.yml` runs only on `wb-ci/**` pushes. Its jobs:
  - `plan`;
  - `web`;
  - `py-static`;
  - `py-tests`, matrix of 4 shards with PostgreSQL service containers and throwaway local passwords;
  - `visual`;
  - `summary`.
- All of it is driven by `scripts/ci/wb_checks.py` and `scripts/ci/wb_screens.mjs`. No secrets are used.
- No other workflow runs for `wb-ci/**` or `wb-ci-base`: every other `push` trigger is limited to `main`, and nothing
  opens a pull request. Release, image, single-track, migration-schema-publish and the lane gate are unaffected.
- GitHub push protection (secret scanning) checks every push, because the repository is public. Never commit secrets
  to the workbench.
