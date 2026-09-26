# Editing the Sales Xray UI locally

The owner's stable development target is the `sales-xray-v02-intake` worktree,
branch `codex/sales-xray-v02-intake`, app `apps/sales-xray-web`.

On this machine the root is
`C:/Users/Suyash/.codex/worktrees/sales-xray-v02-intake/authority-closers-platform`.
Open that root in your editor or agy. Do not edit another checkout and expect
port 3016 to change. The tracked process record under
`.tmp/local-sales-xray-production-bridge/processes.json` identifies the actual
running source directory, ports and process start times.

## Main files

| Screen or concern                       | Files under apps/sales-xray-web                                                               |
| --------------------------------------- | --------------------------------------------------------------------------------------------- |
| Upload, progress and report composition | app/acquisition-studio.tsx, app/acquisition-studio.module.css                                 |
| Sidebar and responsive shell            | app/acquisition-shell.tsx, app/acquisition-shell.module.css                                   |
| Global theme tokens and common styles   | app/styles.css                                                                                |
| Saved calls                             | app/calls-library.tsx, app/calls/page.tsx                                                     |
| Login                                   | app/login/page.tsx, app/login/login-form.tsx                                                  |
| Processing visuals and copy             | app/processing-experience.tsx, app/processing-experience.module.css                           |
| Report sections                         | app/dipak-overview.tsx, app/sales-skills.tsx, app/report-moments.tsx, app/report-explorer.tsx |

Normal source saves hot-reload. Configuration or bridge-script changes require
a controlled restart. Use Node 24, pnpm 11 and PowerShell 7.4+:

```powershell
pnpm dev:sales-xray:production:down
pnpm dev:sales-xray:review
```

The app is at `http://salesxray.localhost:3016/`; the workbench is
`http://salesxray.localhost:3016/__review/`. Review mode uses authenticated real
API reads and blocks analysis/data mutations. Captured states have shareable
local URLs within that browser session and expire. Full fixture test mode is
not included in this observed-state patch.

## Moving your UI changes to production

The same app source is built for deployment. Save locally, review the Git diff,
run the relevant frontend checks and production build, then release the exact
reviewed revision to staging and production through the repository pipeline.
Local edits do not automatically publish. Development inspection controls are
excluded from the production build. Keep auth/provider operations separate from
visual edits, and coordinate file ownership with other active editors.
