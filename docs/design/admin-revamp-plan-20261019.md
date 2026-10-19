# Admin revamp: shell, one kit, and the phases (19 Oct 2026)

The owner reviewed admin-dev on 19 Oct 2026: "pathetic UI and UX, not understandable". He wants a massive revamp so that Admin runs the company's back office. This note covers two things:

- the plan for Phase 1 (one kit and one shell);
- the order of the later phases.

Phase 0 shipped to dev the same night:
- 393a0ed2: the API returns every workspace with its kind;
- 18308f40: the person menu, type badges and artifact fixes;
- c8123640: the role line in the rail.

## What exists today (inventory, workbench at c8123640)

| | Sales Xray web (the Android app loads it too) | Admin | Shared packages |
|---|---|---|---|
| Components | 302 `.tsx`, 113 CSS modules | 23 primitives in `app/ui/kit.tsx`, used by 61 files | `@ac/ui`: the learning app's primitives (not used by Sales Xray). `@ac/operations-web`: sign-in, session and API plumbing. `@ac/sales-xray-review-ui`: one form |
| Kits | `ui/kit.tsx`: 24 primitives in 49 files. `report-kit.tsx`: 11 in 12 files. Lightbox chips and toast. Notice center | A fork of the Sales Xray kit, with `Page`, `Unavailable`, `Kbd` and `Toolbar` added | — |
| Tokens | `--lx-*`: 5,384 uses. `--sx-*`: 1,662 uses | `--sx-*`: 1,223 uses. `--lx-*`: 106 uses, through `legacy-bridge.css` | — |
| Shells | `shell/`, `lightbox-shell`, `acquisition-shell`; profile, settings, help and workspace menus | `ui/shell.tsx`: rail, top bar, phone bottom bar, command menu | — |
| Skeletons | One per page (8 or more) | `Skeleton` plus per-page `loading.tsx` | — |

**The problem in one line:** the two apps share no component code.
- `ui/kit.tsx` exists twice. The copies have drifted apart: Sales Xray has `Segmented`, `Avatar`, `InlineEdit` and `Dialog`; Admin has `Page`, `Unavailable`, `Kbd` and `Toolbar`.
- `sx-tokens.css` also exists twice, and the copies differ. Admin added `--sx-info` and the rail and top-bar sizes. Sales Xray has `--sx-scrim` and `--sx-shadow-float`.
- Report screens use a third kit, `report-kit`, whose `Card`, `Tag` and `Empty` overlap the main kit's.

## The plan: fewer components, one place

1. **One package, `@ac/sx-kit`** (`packages/typescript/sx-kit`), used by Sales Xray web, the phone app and Admin.
   - **Tokens:** one `sx-tokens.css`, the union of both copies. The `--lx-*` names become aliases of `--sx-*`, so nothing breaks while screens move over.
   - **About 28 primitives**, merged from the two kits and grouped by job:

     | Group | Primitives |
     |---|---|
     | Layout | `Page`, `PageHeader`, `Panel`, `Card`, `Split`, `Toolbar` |
     | Data | `Table`, `List`/`Row`, `Tiles`/`Kpi`, `Spark`, `Meter`, `Delta`, `Fact` |
     | Status | `Badge` (it absorbs `Tag`, `StatusChip` and `IconBadge` as tones), `Empty`, `Unavailable`, `Skeleton`, `Why` |
     | Input | `Button`, `Field`, `Segmented`, `QueryTabs`, `InlineEdit`, `Dialog`/`Sheet`, `Menu`/`Popover`, `Kbd` |
     | People and places | `Avatar`, `PersonMenu`, `WorkspaceBadge` |
     | Feedback | `NoticeCenter`: corner cards and toasts. Never red banners |
2. **One shell: `AppShell`.** It has:
   - a rail of grouped sections;
   - a slim top bar with the environment and Go to;
   - on phones, a bottom bar with More;
   - the person menu (Phase 0) at the top.

   Admin adopts it first. Sales Xray web adopts it next, screen by screen, behind the same tokens, so the phone app looks the same as the web.
3. **Call components shared by the Report and Admin** go in `@ac/sx-call-ui`, built in Phase 2:
   - player;
   - transcript;
   - voice;
   - timeline;
   - facts and objects table.

   Today Admin has its own copies (`calls/engine-objects`, `transcript-pane`, `player`), and Sales Xray web has `report-visuals` and `xray-report`.
4. **Rules from now on:**
   - a new screen imports only from the kit;
   - no raw colours;
   - each move replaces one screen's imports with no visual change, checked with the loopback screenshot harness at 390, 1024 and 1440 px in light and dark;
   - skeletons are the same size as the content, so nothing shifts when it loads.

**The order of work:**
1. Create the package, with Admin's kit as the base, plus the four primitives only Sales Xray has, and the union of the tokens.
2. Move Admin onto it, which needs only the import path to change.
3. Build the new Admin shell on it.
4. Move Sales Xray web over screen by screen, Lead Desk and Review first, because the phone uses them most.

## The new Admin shell (built in Phase 1, after 08:00 IST)

- **Environment switch** in the top bar: Development, Staging, Production.
  - Production Admin reads all three: metrics already do, and calls, health and settings follow.
  - Each page says which environment a number comes from.
  - Writes stay per environment until the Admin API (Phase 6) carries the environment on every command.
  - This is how one Admin on production controls dev and staging, as the owner asked.
- **Rail by job:**

  | Group | Sections |
  |---|---|
  | Today | Home: what needs a decision |
  | Calls | Calls, Review, Gold set |
  | Insights | Company, Analysis health, Usage & cost, Deal outcomes |
  | Setup | Providers & models, Analysis, Call data, Report versions, Budget and caps |
  | Accounts | Organisations, People, Reviewers |
  | Platform | Releases, Product updates, Safety, Academies |
- **Settings:** one page lists every setting with its current value, who changed it and when, and a one-click change for each.
  - The same registry backs the Admin API, the CLI and the MCP tools (Phase 6), so a person or an AI changes a setting the same audited way.
- **Dense by default:**
  - row height 36 px, numbers in tabular figures;
  - filters live in the address, so every view can be linked;
  - keyboard: Go to with Ctrl K, J/K to move, Enter to open.

## Later phases (each ships to dev when ready, then to Align 3)

| Phase | What | Depends on |
|---|---|---|
| 2 | **Calls and call detail.** A dense list you can filter. Call detail shows: the call objects; voice; timeline; facts, with who made each and its status; every run and stage with time, tokens and cost; the raw provider output. The Pipeline map becomes a proper node graph: fast and deep branches, skipped and waiting stages, and cost on each edge. | Interfaces agreed with the call-data-engine chat, which owns the data and APIs |
| 3 | **Review 2.0.** Reviewers judge the analysis objects in sales and psychology terms, not the report layout. Coaching review is separate. Review pipelines are configurable, built from base steps: pick a sample, show an object, ask a question, record a verdict, settle disagreements. It reuses the 0094 gold rows. | The gold-review work (d5116a31, 53821a5d) |
| 4 | **Insights.** Usage & cost: pick charts, compare two, cost per call. Analysis health and Company with real figures: skill states, objections, outcomes. | Pune sandbox data (AUT-2116); the Admin metrics chat's store |
| 5 | **Model bench.** Run the gold set and sample calls across every provider configured in Admin, and compare cost, latency and quality. | Keys from the owner via Infisical, and a spend ceiling. Ask the orchestrator first |
| 6 | **Admin API, CLI and MCP.** Every setting can be read and written, audited and role-checked, with the environment on every command. | The Phase 1 settings registry |

## Found in Phase 0 (data, not code)

- **"Authority Closers" for admin@:** the display name of the `admin@authorityclosers.com` account is "Authority Closers" on dev and production. So the Calls list and the person menu show a company name where a person belongs. This is account data, so it was proposed to the orchestrator as a recorded data change.
- **The "empty duplicate" Authority Closers on production** is not an organisation. It is the operations tenant `fb594dea`: Admin roles, no calls. Admin now calls it "AC Operations · Staff" and shows its registered name in the menu.
