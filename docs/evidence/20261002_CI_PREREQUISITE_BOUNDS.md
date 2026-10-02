# Bounded CI codec, filesystem and browser prerequisites (AUT-575)

## Problem

Application validation run 36739446989, attempt 1, failed Python shard 2 at
`Install locked Python browser runtime` (15:59:59–16:05:12 UTC, 30 Sep). The log
showed apt mirrorlist requests right before the stall; the five-minute step cap
fired, the shard never ran and its evidence upload failed. Three jobs ran two
unbounded `apt-get update`/`install` sequences each: one for ffmpeg (and
e2fsprogs/util-linux), then a second, hidden one inside
`playwright install --with-deps chromium`.

## Change

- `scripts/ci/ci_prerequisites.py` installs and proves the components a job
  names (`codec`, `filesystem`, `browser`):
  - apt runs as `sudo timeout --kill-after=10s <n>s env DEBIAN_FRONTEND=noninteractive apt-get`
    with `Acquire::Retries=2`, 20 s HTTP(S) timeouts and a 60 s dpkg lock wait.
    Root runs `timeout`, so a stalled apt/dpkg process is killed, not only sudo.
  - Update 120 s, install 300 s, browser download 240 s per attempt; 3 attempts
    with 5 s/15 s backoff; one 720 s overall budget. A killed install runs
    `dpkg --configure -a` before its retry. Exhausting attempts or budget prints
    a GitHub `::error::` and exits 1 (fail closed).
  - Packages already installed are not fetched; when nothing is missing, apt is
    not touched at all. Codec and browser system libraries go in one apt
    transaction instead of two.
  - The Chromium system package list comes from the locked Playwright's own
    `install-deps --dry-run chromium`; the browser comes from
    `python -m playwright install chromium` in the same `uv run --frozen`
    environment. No lock or version changes.
  - Proof after install: `ffmpeg`/`ffprobe` present and `-version` succeeds;
    `mkfs.ext4`, `losetup`, `mount`, `umount`, `findmnt` present; locked
    Chromium launches headless and renders a page.
- `.github/workflows/application.yml`: each of the three jobs now has one
  `uv run --frozen python scripts/ci/ci_prerequisites.py <components>` step
  (13-minute step cap, above the helper's 12-minute budget) in place of the
  separate apt and `playwright install --with-deps` steps. Job caps, the four
  Python shards, coverage aggregation and evidence retention are unchanged.

## Verification (local, 2 Oct 2026)

- `uv run --frozen pytest -q tests/infra/test_ci_prerequisites.py tests/infra/test_recovery_ci_gates.py tests/infra/test_registration_browser_gate.py`:
  62 passed. New regressions cover: present packages skip apt; missing packages
  install once with bounded root timeouts and apt network options; an apt
  mirror stall fails closed after 3 attempts without installing; a killed
  install repairs dpkg before retrying; the overall budget caps attempts;
  browser download and launch failures fail closed; an unreadable Playwright
  package list fails closed; the real locked Playwright list parses; a timed-out
  process group is killed with its children; each job has exactly one bounded,
  frozen prerequisite step before first use; no `apt-get` or `--with-deps`
  remains in the workflow; shards, coverage and evidence are unchanged.
- Host smoke (no sudo): locked Playwright reports 33 Chromium packages;
  `playwright install chromium` ok; Chromium 145.0.7632.6 launches headless;
  ffmpeg/ffprobe 6.1.1 prove.
- Ruff lint/format, mypy on the helper and Prettier on the workflow pass.
- Clean GitHub-hosted runner proof is the PR's Application validation run.
