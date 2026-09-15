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

## Coordinator integration and browser verification

Integrated with the personal report/quota leaf in
`authority-closers-xray-personal-report-20260914`. Conflict resolution retains
both confirmed/unknown quota handling and the stage rail.

Review corrections: failed/cancelled source checks and uncertain processing stay
static; an unconfirmed C2 result never claims a completed transcript. Running
stages take precedence over future queued work. Older uncertain rows do not
override a later returned state for the same stage. A completed C4 chunk without
evidence of the next stage is labelled `Work saved`, not full-stage completion.
Partial work is described as `Some conversation analysis is saved`.

The stage markers shown to users are 1/2/3. Internal C2/C4/C5 names remain in
the API/data attributes. Once submitted, the onboarding hero and promotional
aside give way to a single focused processing panel. No provider retry, purchase,
new upload or automatic recovery was added.

- Combined UI suite: 133 passed, 17 files, 12.60s; actual
  `D:/AC-authority-closers-release-audit/personal-report-20260914/ui-integrated-final.xml`.
- After the final focused layout change: all 17 mounted acquisition tests passed;
  `progress-layout-final.xml` in that directory. The initial integration run's
  16 passes/one failure are retained separately: its running fixture incorrectly
  said automatic progression was disabled and was corrected to the API's active
  plan shape. No production contract was relaxed.
- Final optimized build and TypeScript phase passed; `build-progress-layout-final.log`.
- Real browser + local fixture HTTP checks cover running C4, partial held C4,
  uncertain C2, exact remaining allowance, hidden onboarding after upload,
  paused SVG motion, reduced-motion and 390px fit. See `progress-browser-final.json`,
  `progress-held-desktop.png`, `progress-held-mobile.png`, and
  `progress-running-desktop.png` beside the JUnit. Browser state scenarios are
  explicitly synthetic and make zero provider calls.
- Source/model/runtime fixes and authenticated live deployment tests remain owned
  by the release task; this is not a successful hosted inference receipt.
