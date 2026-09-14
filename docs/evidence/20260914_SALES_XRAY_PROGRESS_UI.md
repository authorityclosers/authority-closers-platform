# Sales Xray acquisition progress UI evidence

Date: 2026-09-14  
Worktree: `authority-closers-xray-progress-20260914`  
Branch: `codex/sales-xray-progress-20260914`

## Implemented behavior

- The acquisition processing panel renders the fixed C2, C4 and C5 stages from the server progress rows.
- Stage labels use the returned row state (`Complete`, `In progress`, `Queued`, `Not started`, or `Paused · needs attention`). The UI does not calculate percentages, totals, or synthetic completion counts.
- A held plan or an `uncertain` stage shows `SAVED WORK · PAUSED`, names the paused stage, keeps completed work visible, and explains that the recording does not need to be uploaded again.
- The paused path has no automatic retry, re-upload, or paid recovery action. Existing explicit deletion remains available.
- The processing signal is hand-coded SVG with restrained orbit motion. `prefers-reduced-motion: reduce` disables the animation; the paused signal remains static.
- Waiting copy gives two short, non-operational coaching prompts while the server continues processing.

## Verification

- Mounted Vitest: 9 tests passed in `apps/sales-xray-web/app/acquisition-studio.test.tsx`.
- JUnit receipt: `D:\AC-authority-closers-release-audit\sales-xray-progress-20260914\vitest-acquisition-junit.xml`.
- ESLint (`--max-warnings 0`): passed.
- TypeScript typecheck (`tsc --noEmit`): passed.
- Prettier check: passed for the three changed acquisition files.
- `git diff --check`: passed.
