# Parallel lanes: one task per lane, three lanes (29 Sep 2026)

## Decision

The owner chose "3 lanes + Luna swarm" on 29 Sep 2026. It replaces "one task at a time for the whole company", which left a 13-task queue running strictly in series. On the same day the owner also delegated merge approval to the CEO; this change folds that into AGENTS.md too (it replaces AUT-44).

## What changed

- `scripts/ac_task.py`:
  - Lanes `sales-xray`, `platform` and `admin`, each with one task branch `task/<lane>/<issue>-<name>`.
  - A plain `task/<issue>-<name>` branch stays **exclusive**: it runs alone, as before, so existing branches and habits keep working.
  - `status --json` gives per-lane automation data.
  - `pr-check` is the new CI rule. A pull request fails while:
    - its lane is taken;
    - an exclusive task is open;
    - it changes a file another open pull request changes;
    - it and another open pull request both change shared files (migrations, lockfiles, workflows, AGENTS.md, the gate, the model registry).
- `.github/workflows/single-track.yml`: runs `pr-check` from **main's** copy of the gate, never the pull request's own, so a pull request can't weaken its check. Until this change is on main it keeps the original one-pull-request rule. The job keeps its name, so branch protection is unchanged.
- `AGENTS.md`:
  - rules 1–3: lanes, one checkout per lane;
  - rules 4–5: the CTO reviews, the CEO approves, and the watchdog merges exactly the approved commit. The owner still decides on billing, payments, purchases, secrets, production data and data deletion;
  - rule 7: agents run in parallel within the launcher's server headroom.

## Server side (outside git)

- Lane checkouts live at `/home/acdev/src/lanes/{platform,admin}/authority-closers-platform`. The `sales-xray` lane keeps the dev checkout, so salesxray-dev shows its work live.
- The per-lane test databases `ac_test_lane_{platform,admin}` sit in `acdev-test-postgres`, and the `ac-test-lane-dbs.timer` recreates them after restarts.
- The agent launcher maps agents to lanes (`~acdev/.config/acdev/lanes.conf`) and sets each lane's checkout and test database.
- The watchdog starts the next runnable task in every free lane (from the `Lane:` line on the task). When a pull request falls behind main, it updates the branch; approvals carry over a pure catch-up merge.

## Evidence

- `tests/infra/test_ac_task.py`: 32 tests pass, 20 existing and 12 new for lanes, exclusivity, `status --json` and `pr-check`.
- Ruff check and format are clean.
