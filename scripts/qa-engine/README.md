# Sales X-Ray QA robot (engine b)

A scripted test robot for Sales X-Ray. **Dev only, sandbox organisations only, scripts only (no AI in the loop).**
It signs in as fictional sandbox people, walks the app, checks what is on screen and in the network log, and files every
failure through the app's own bug reporter (`POST /v1/bug-reports`, with a picture) and into the persona journey matrix.

## Rules it keeps

- Dev only. It never touches production, staging or the real AC organisation. A page opened as the owner is refused unless the
  workspace label says "Sandbox".
- Writes are held 1.2 s and refused for everything (lib/sim.cjs `holdWrites`); any other same-origin write is refused outright.
  Journey scripts that need writes run only in the AC Sales Sandbox and Fortline sandbox organisations, on records the script
  creates ("QA robot" names), and undo or delete them at the end.
- No secrets in this folder or in its output. Sign-in is a plain HTTP call to persona-qa's proxy (`/__as/<alias>`); the cookie
  stays in memory. Passwords live only in that proxy and in Infisical.
- It waits while dev is rebuilding or its pages do not compile, while a PAUSE file exists, while dev `/v1` answers slower than 2 s,
  and while the box is under memory or CPU pressure. A STOP file ends it.
- Nothing is filed while dev pages do not compile.

## What is here

- `engine.cjs` the CLI: `rows`, `sweep <axe|visual|monkey|crawl>`, `sim`, `attack`, `mixed` (rows, one persona walk, then state attacks),
  `digest`, `rejudge`, `scope`.
- `lib/clickmap.cjs` + `data/click-map.json` the 99 click destinations of the Home and Leads handoff as checks.
- `lib/plans.cjs` read-only journey plans (one function per journey id).
- `lib/sim.cjs` seeded persona walks; `lib/invariants.cjs` the checks run after every step.
- `lib/attack.cjs` state attacks: fault injection, 3G, data extremes, text zoom, keyboard-only, dark mode, Back/Forward/refresh
  mid-flow, double submit. One cell is one page x size x role x family; the least recently run goes first.
- `lib/report.cjs` filing: fingerprint `area|route|rule:selector`, a repeat inside 12 h is counted (+1), not re-filed.
- `lib/guard.cjs` headroom, `lib/rebuild.cjs` the dev-rebuild detector, `lib/session.cjs` browser and sign-in.
- `matrix.py` thin wrapper around persona-qa's `qa_matrix.py` (claim, release, sweep, annotate).
- `selftest.cjs` pure checks that need no browser or server; run by `tests/unit/ci/test_qa_engine.py`.

## Running it (on the dev box)

Needs Node 20+, Playwright with Chromium, and `deps.json`'s packages (`npm install --prefix <dir>`; set `NODE_PATH` to that
`node_modules` folder). Configuration comes from the environment, never from this folder:

| variable | meaning | default |
| --- | --- | --- |
| `QA_PROXY` | persona-qa's pass-through proxy | `http://localhost:3098` |
| `QA_MATRIX_DIR` | folder of the matrix CSVs and `qa_matrix.py` | `/home/acdev/qa-matrix` |
| `QA_STATE`, `QA_OUT`, `QA_BASELINES` | where ledger, pictures and baselines go | next to the code |
| `PLAYWRIGHT_PATH` | the `playwright` package folder | the workbench's |
| `QA_DEV_HOST`, `QA_API_PORT` | the dev site's host name and the API port, for the latency probe | see `lib/guard.cjs` |
| `QA_ATTACK_PER_TURN` | attack cells per mixed turn | 6 |

Agent jobs run only in `ac-strikes.slice`, one worker. A foreground test: `node engine.cjs attack --dry --verbose --family
keyboard --page /dashboard --size "390 px"` (dry mode files nothing).
