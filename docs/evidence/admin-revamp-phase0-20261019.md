# Admin revamp, Phase 0: evidence (19 Oct 2026)

**Owner's review (19 Oct):**
- "Pathetic UI and UX, not understandable."
- Signing in shows "Authority Closers" twice, then "Public Learners", then "Sandbox".
- He wants to see the person who is signed in, then every organisation and account labelled by its type.

## Commits (workbench, live on dev)

- **393a0ed2:** API.
  - New: `GET /v1/platform/workspaces` (`platform_tenants_read`).
  - New: `ac_platform/organisations/workspace_kinds.py`. It sorts workspaces into company, customer, personal, sandbox, operations and other, using settings and recorded flags, never names.
  - The Calls list, call detail and the Company picker return clear names plus `organisation.kind`.
- **18308f40:** web.
  - Person menu at the top of the rail, with workspaces grouped by kind, type badges, people and call counts, and the registered name when it differs.
  - AC Admin and the environment at the bottom of the rail.
  - Badges in the Calls list.
  - Artifact fixes:
    - sparklines spilled into the next tile;
    - tile notes were cut off;
    - Voice and timeline content touched the card edge.
  - Report settings: "Default (Version N)", and no more one-option menu.
- **c8123640:** the rail shows only the role ("Owner"); the full line is in the panel.

## Checks

- **Python (on ac):**
  - ruff, ruff format and mypy are clean on the changed files.
  - pytest: platform workspaces (2 new), platform organisations, admin call review, admin insights routes and insights route. 33 passed.
- **Web (workbench):**
  - tsc 0, eslint 0, prettier clean.
  - vitest: 78 files passed. The shell suite has 9 tests, 2 of them new for the person menu.
- **Classification rule against real data (read-only SQL, dev and production):**

  | Environment | Workspace | Kind |
  |---|---|---|
  | Production | `02150758` Authority Closers | company |
  | Production | Estate Autopilots | customer |
  | Production | `c1d51741` | personal, shown as "Personal accounts", registered as "Authority Closers Public Learners" |
  | Production | AC Sandbox | sandbox |
  | Production | `fb594dea` | operations, shown as "AC Operations", registered as "Authority Closers", 0 calls |
  | Dev | the same, without Estate Autopilots | |
- **Route on the dev live API:** returns 401 without a session, the same as `/v1/platform/organisations`.

## Captures

- Loopback harness:
  - `stub_shell.py` serves the shell's identity reads and a directory exported from dev by read-only SQL, in the endpoint's shape;
  - `next dev --webpack` runs from a scratch copy, so admin-dev never stopped;
  - Playwright.
- Files are in `ac:/home/acdev/strikes/admin-revamp/shots/2026-10-19/`:
  - `menu-desktop-dark.jpg`, `menu-desktop-light.jpg`, `rail-desktop-dark.jpg`, `menu-tablet.jpg`, `menu-phone.jpg`;
  - `report.json`: no horizontal overflow at 1440, 1024 and 390, no page errors, the panel open at 340×470.
- The harness scripts are next to them.

## Not done in Phase 0

- **admin@'s display name.** It is "Authority Closers", account data. A rename was proposed to the orchestrator as a recorded data change.
- **The cost metrics label** "Individuals (personal accounts)" and the report-settings organisation names. Both are in files the Admin metrics chat owns; it was asked to switch to `classify_workspaces` / "Personal accounts".
- **Analysis health and Company figures** (every skill at 100%, 0 objections). That is Phase 4: it is the data, not the layout.
