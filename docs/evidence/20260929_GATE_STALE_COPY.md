# AUT-94 gate stale-copy evidence

Date: 2026-09-29

## Verification

- `uv run pytest tests/infra/test_ac_task.py -q` — 40 passed.
- `python3 scripts/ac_task.py check` — `ok: task/platform/94-stale-gate-guard may be worked on` while this task branch edits `scripts/ac_task.py`.
- `python3 scripts/ac_task.py status` — printed one verdict line for each lane and one exclusive verdict. The command returned exit 3 because multiple lanes were active; the output included:

```text
sales-xray: BUSY: another task is in progress in the sales-xray lane: task/sales-xray/81-http-source-readers; open pull request(s): #104 AUT-55: Resolve sources in all three HTTP playback routes
platform: BUSY: another task is in progress in the platform lane: task/platform/94-stale-gate-guard
admin: BUSY: another task is in progress in the admin lane: task/admin/57-github-metrics; open pull request(s): #108 AUT-57: Add GitHub scorecard metrics
ui: BUSY: another task is in progress in the ui lane: task/ui/66-shell
exclusive: BUSY: another task is in progress: task/admin/57-github-metrics, task/platform/94-stale-gate-guard, task/sales-xray/81-http-source-readers, task/ui/66-shell; open pull request(s): #108 AUT-57: Add GitHub scorecard metrics; #104 AUT-55: Resolve sources in all three HTTP playback routes
```

## Refusal text asserted by the new tests

```text
ac_task: current task branch task/ui/66-shell is missing from GitHub; run `python3 scripts/ac_task.py done` first
ac_task: running scripts/ac_task.py differs from origin/main:scripts/ac_task.py; run `python3 scripts/ac_task.py done` first
ac_task: running scripts/ac_task.py differs from origin/main:scripts/ac_task.py; run `git switch main && git merge --ff-only origin/main` first
```

The tests also verify that a matching gate starts from `origin/main`, that the fetch happens before the comparison, and that `check` does not compare the current gate file with main. A stale gate on a `task/*` branch uses the `done` remedy; a stale gate on `main` directs the operator to update local main before trying again. `start` does not switch branches or push in either refusal case.
