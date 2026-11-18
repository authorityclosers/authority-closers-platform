# QA system, stage 1 (Sales X-Ray side)

Owner, 18 Nov 2026: "How come there are bugs that are just visible?", then "Yes, start stage 1". The plan is the QA
system research of 18 Nov (sections 4 and 6). Everything here runs with no model and no tokens, except `judge.mjs`.

| What                 | File                                                              | Where it runs                                  | Blocks?                                |
| -------------------- | ----------------------------------------------------------------- | ---------------------------------------------- | -------------------------------------- |
| Readability Gate     | `scripts/ci/wb_readability.mjs` (+ `_lib`, baseline)              | wb-ci, job `readability`, on every full run    | Yes: anything new against the baseline |
| Role walk            | `scripts/qa/role-walk.mjs`                                        | ac, against dev through the persona proxy      | No: a report, exit 1 on a failed page  |
| Production monitor   | `scripts/qa/monitor/` (unit `ac-qa-monitor`, every 15 min)        | ac, against production's edge on loopback      | No: `state/RED.md` when red twice      |
| Nightly check        | `scripts/qa/nightly/` (unit `ac-qa-nightly`, 21:00 UTC)           | ac, against production's edge on loopback      | No                                     |
| Phone smoke          | `scripts/phone_smoke.py`                                          | the PC with the Redmi 13 on adb, after a build | No: exit code per outcome              |
| Screen judge (model) | `scripts/qa/judge.mjs`                                            | wherever a Claude CLI is signed in             | No: one verdict for one question       |

## The QA identity

Never test as a real seller, and keep test data out of every number (owner, 17 Nov 2026).

- **Production:** the QA account (a fictional person, the `+ac-qa-production` alias; its sign-in lives in
  `/home/acdev/.config/ac-qa/production-account.env` on ac, mode 0600) is a Member of **TEST · Sahyadri Homes**. That
  workspace is flagged as a sandbox: every lead in it is test data, its Call button dials nobody, and telemetry and
  the lake leave it out. It was added with `scripts/data-changes/sandbox-persona.py` (snapshot, dry run, apply,
  read-back).
- **Dev:** four fictional people, signed in by the persona proxy on ac (`/__as/<alias>`), passwords only in Infisical
  dev `/sandbox-logins`:

  | Role    | Alias       | Workspace                                    |
  | ------- | ----------- | -------------------------------------------- |
  | Owner   | `qaowner`   | TEST · QA Owner Desk (its own)               |
  | Admin   | `anjali`    | AC Sales Sandbox (the owner-view person)     |
  | Manager | `qamanager` | TEST · Sahyadri Homes                        |
  | Seller  | `qa`        | TEST · Sahyadri Homes (the QA account's twin) |

## Readability Gate

```sh
node scripts/ci/wb_readability.mjs <out> [--origin http://127.0.0.1:3026] [--only home,leads-list] [--shots]
node scripts/ci/wb_readability.mjs <out> --write-baseline [--prune]   # after a fix removed findings
```

The top 20 screens (review fixtures, fictional data) x 4 corner states (360 px dark at 130% text, 360 px light,
1280 px light and dark) x plain and long real-shaped data = 160 loads. Each load runs the radar's scan, the overlap
scan, the contrast scan, axe-core and the gate's own checks. A new finding fails the run; a load with something new is
measured three times and only what every pass saw counts. Findings already in `scripts/ci/wb-readability-baseline.json` do
not block: that file is the list of known problems to work down. Make the baseline on the machine type that checks it
(the hosted runner): take `readability.json` from a run's `wb-readability` artifact, never a laptop's.

To add a screen: one line in `SCREENS` (`wb_readability_lib.mjs`), then record its cells into the baseline.

## Role walk

```sh
LD_LIBRARY_PATH=/home/acdev/qa-engine/chromelibs node scripts/qa/role-walk.mjs /var/tmp/role-walk [--roles seller]
```

Opens every menu item the app shows each role, on a phone and a laptop. It fails a page on a refusal, an error page,
a blank page, the terms box, junk on screen, an uncaught error or a 5xx. It only reads.

## Production monitor

`sudo bash scripts/qa/monitor/install.sh --enable` installs `/home/acdev/qa-monitor` and the timer. It is read-only:
every request that is not a GET is refused in the browser, except the QA account's own sign-in and its session's
workspace choice. Read `state/status.json` for the latest run; `state/RED.md` exists while the same failure has shown
twice in a row.

## Phone smoke

```sh
python scripts/phone_smoke.py 7505cec
```

Exit 0 green, 1 a screen failed, 2 phone unreachable, 3 the app is signed out, 4 the phone is busy (the Live design
app is in front), 5 signed in but not to a TEST workspace (it stops: never test as a real seller). It presses only the
bottom bar. The Redmi is shared with the Mac's sessions: claim it in the Mac's inbox before a run.

## Screen judge

```sh
node scripts/qa/judge.mjs --after after.png --before before.png --question "Is the primary action still obvious?" \
  --model sonnet --crop 0,80,363,300
```

One narrow question, small pictures, a fresh session, `--model haiku|sonnet|opus|fable` (sonnet by default). It
refuses questions about overflow, overlap, cut text, contrast or tap size: the gate measures those.
