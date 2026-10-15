# Report timeline clip playback — AUT-1663, 11 October 2026

Implementation: `67992169` on the shared `dev/live` workbench. Scope: owned shared Report primitives only.

The timeline's moment pins previously always offered Play, even while the report's shared audio player played that excerpt. They now use the existing `ClipPlayState` contract, just like `PlayChip`. The active pin has a steady halo, exposes `aria-pressed="true"`, and offers Pause in its accessible and hover labels. Pausing or reaching the excerpt's end clears it. A different overlapping clip and full-recording playback do not claim that this clip is playing. The pin still forwards the original evidence range to the studio's existing player; no separate player or new playback decisions were introduced.

This is a bounded interaction repair using existing Report components, copy and semantic colour tokens. The binding design source remains `/home/acdev/scratch/specs/final-xray-structure-2026-10-09.md` (the timeline and playable moments). Spec source SHA-256: `a464e69123f9a649f5f038e464d6086c6d52220b09e3e50eb24b44c6769e3110`. No new scoring, data writes, provider run, deployment or business interpretation is involved. AC Orchestra Pro skill/session access is unavailable on this seat; no cloud-created design or artifact is claimed.

Validation:

- Both new regressions failed before the repair because the pins exposed no playback state.
- 29 focused cases pass across `report-visuals/playback.test.tsx`, `visuals.test.tsx`, `timeline.test.ts` and `clip-listen-button.test.tsx`. The playback regression uses actual audio state/events through `SourceWaveformProvider`, checks agreement with PlayChip, pause, the cited end, overlapping ranges and full-recording playback.
- Incremental TypeScript check includes both changed TypeScript files and their imports. Cached ESLint, formatting and `git diff --check` pass.
- Shared-dev timeline readback passes 4/4 cases at 1440/390 px, light/dark: actual clip playback, Pause label/steady halo, pause, resume and stop at the cited end. Eight playing/paused PNGs were visually inspected; no page errors or sideways overflow. The ordinary studio/player on `http://127.0.0.1:3026` uses the existing fictional Dipak overview with five seconds of generated silence. Every API write is refused; each case records two existing automatic prospect-detection requests blocked with 405, and no additional request caused by playback.

Receipt: `/home/acdev/strikes/1663/shots/2026-10-11/timeline-playback-scoped/receipt.json`, SHA-256 `31d4480cfe38499176d0b6f7e47bff0bf26e06c6f4194f0d3428b07a28f8a37b`. Source HEAD moved from `ffca886c174d36b39627db3e4d40a02a895ca974` to `1864b5a977dff2012be7a5d074ba065b5fd626b8` while other agents committed; the owned Report primitive files remain unchanged from `67992169`. This is live-workbench fixture evidence, not an immutable release or real-account/production acceptance.

All screenshots are in that receipt's directory:

- `timeline-1440-light-playing.png` — the active moment's steady warm halo and line, with the shared dock playing.
- `timeline-1440-light-paused.png` — the halo clears and the same dock offers Play.
- `timeline-1440-dark-playing.png` — the active moment remains distinct on the dark wave.
- `timeline-1440-dark-paused.png` — the paused pin returns to its plain dot.
- `timeline-390-light-playing.png` — the same active moment on the phone's full-width wave.
- `timeline-390-light-paused.png` — the halo clears without moving the phone layout.
- `timeline-390-dark-playing.png` — the halo and measured speech bars remain readable in dark mode.
- `timeline-390-dark-paused.png` — the pin and dock both reflect pause.

The earlier receipts in `timeline-playback-first/`, `timeline-playback/` and `timeline-playback-final/` are retained as incomplete. They respectively encountered an overbroad pressed-button selector including folded map tabs, the deliberately blocked prospect-detection requests, and a separate full-player dock click intercepted by Report content after excerpt completion/scroll. The final check is scoped to the owned timeline interaction. Full-recording exclusion is verified by the provider regression; the separate dock click journey is not claimed as passing.

The finite browser and all contexts exited normally. No server, watcher, provider execution or data mutation was left running.

## Recording-dock follow-up: classify the retained failure

Coordinator request: 11 October 23:23 UTC. The bounded audit claims only the four existing `call-audio-dock` source/test paths and the already owned evidence file. No Report composition or other owner’s source was changed.

The retained failed receipt `timeline-playback-final/receipt.json` is unchanged (SHA-256 `e48b69ced6033bcb980ecdd470cb83f79613de5bccde800c88acaccf5204093c`). It records pointer interception but lacks dock-state diagnostics, so the historical receipt alone is not treated as proof of a visible control being covered. A shared-dev reproduction after the same timeline excerpt-end phase restores the paused-dock scroll / ordinary locator-click sequence, with non-mutating scroll and dock-attribute observers. Its click timeout is six seconds; the original receipt’s timeout was thirty seconds.

The reproduced failure follows the existing auto-hide contract, rather than a covered shown control:

| Stage | Closest scroller (`studio-main`) | Revealed / playing | Dock bounds | Style / centre hit |
| --- | --- | --- | --- | --- |
| Before scrolling the paused dock | 691 px | true / false | x 400, y 786, 952 × 62 px | opacity 1, pointer-events auto; centre hits Play |
| Before the original click | 1082 px | false / false | x 384, y 848, 952 × 0 px | opacity 0, pointer-events none; centre hits Report content |
| After click retries | 3151 px | false / false | x 384, y 848, 952 × 0 px | opacity 0, pointer-events none; centre still hits Report content |

The event receipt records the 391 px scroll while paused, immediately followed by `data-revealed=false`. The source hides a paused, non-embedded dock after its closest scroller moves more than 120 px; the stylesheet then clips it to zero height and disables pointer events. The element’s descendants retain button bounds, explaining why the runner could find a button and still have its pointer intercepted. A revealed control’s centre hit succeeds, and its ordinary full-recording click, playback beyond the prior excerpt end and keyboard pause/resume pass. No product defect or code repair is asserted.

Classification receipt: `/home/acdev/strikes/1663/shots/2026-10-11/recording-dock-classification/receipt.json`, SHA-256 `87409acd3ec5366c5ac2b416b636412a9c12bcb99bc774c00e9d13ecedd82d9f`; source HEAD `d224e61596a8613ac48beea952ffcb74be8aaf25` throughout. Both PNGs inspected: `dock-1440-light-original-click.png` shows the intentionally absent dock; `dock-1440-light-full-recording.png` shows the ordinary recording control playing above the Report.

All four assigned dock files are byte-identical to retained failure source `9ee9cf6b`. Runtime/source SHA-256 pins: `call-audio-dock.tsx` = `074f8948d5f7479e57bcef886db2b2814e03f5d4494939dd7f9be6958216046d`; stylesheet = `c812e256b2bba3fb806560234f75ff16c65157d091e909eab3eb1c43168f49a7`. The existing unit/layout test files also remain unchanged; there was no TypeScript product change requiring a new typecheck or unit-test run.

The broader normal-pointer runner preserves every existing timeline assertion (active halo and Pause label, pause/resume, excerpt-end stop), clicks the already shown full-recording button at its actual centre, and then explicitly tests the paused-scroll hide and playing-scroll keep-open contracts. It never clicks a hidden control, forces a click, patches component state, bypasses excerpt bounds or removes the original failed proof. The earlier `recording-dock-regression/receipt.json` and `recording-dock-final/receipt.json` are retained as incomplete: full playback passed, but the five-second silent source ended before the keyboard step. The final runner uses 0.25× actual playback from the shown full-recording click, leaving time for screenshots and keyboard activation while still measuring natural playback beyond the excerpt end. This is a runner timing correction; the player source is unchanged.

Accepted responsive matrix (four passing cases across two retained runs, rather than a claimed four-case clean launcher):

| Case | Receipt | Shown full-control centre | Actual full-recording time after the stopped excerpt | Paused / playing scroll checks |
| --- | --- | --- | --- | --- |
| 1440 / light | `recording-dock-verified` | (431, 817), hits button | 3.167 → 3.663 seconds, still playing | paused +160 px hides; playing +160 px remains shown |
| 1440 / dark | `recording-dock-verified` | (431, 817), hits button | 3.180 → 3.670 seconds, still playing | paused +160 px hides; playing +160 px remains shown |
| 390 / light | `recording-dock-phone` | (63, 656), hits button | 2.273 → 2.849 seconds, still playing | paused +160 px hides; playing +160 px remains shown |
| 390 / dark | `recording-dock-phone` | (63, 656), hits button | 2.464 → 2.842 seconds, still playing | paused +160 px hides; playing +160 px remains shown |

Each accepted case preserves active pin/Pause label/steady halo, timeline pause/resume and excerpt-stop assertions; a normal pointer at the shown recording control then clears clip attribution and plays beyond that prior stop. Space pauses/resumes the same button. Paused scrolling hides the dock; replaying an actual clip restores it; playing scrolling keeps it shown; the normal Hide player click pauses and hides it. No page errors, sideways overflow or playback-caused API writes in these cases. The two existing automatic prospect-detection attempts per case are explicitly blocked with 405 and retained. Twenty accepted-case screenshots were individually inspected.

`recording-dock-verified/receipt.json` has two accepted desktop cases, followed by a five-second timeout on the phone timeline's existing excerpt-stop assertion before any dock step. That timeout remains an unexplained, incomplete phone attempt; it is not erased or presented as a passing launcher. A narrow phone retry with media-failure diagnostics and the identical timeline assertions passed both themes; no product code, stop assertion or timeout threshold was changed.

Receipt and source pins:

- `recording-dock-verified/receipt.json`: SHA-256 `d5460f58b6787e9034631b37694f7bf62930bf14e19fd1c357cc68e94cc3fac8`; repository HEAD `d224e61596a8613ac48beea952ffcb74be8aaf25` → `57fd8db71b67c5f7eb6bc258b3b8e1d6509234d5`.
- `recording-dock-phone/receipt.json`: SHA-256 `77fb6857512d15e9e871b90709a1a6bd7ce28618b3306dec1f76da0ae9d04053`; repository HEAD `57fd8db71b67c5f7eb6bc258b3b8e1d6509234d5` → `57fd8db71b67c5f7eb6bc258b3b8e1d6509234d5`.
- Current retained runner `/home/acdev/strikes/1663/tools/recording-dock.mjs`: SHA-256 `063b76c9b6469bf2f439af6532497e1d560977ab25ec95255ceff77f4808e59d`; Node syntax check passes. The phone runner adds only failure diagnostics to the desktop runner's assertions.
- Current retained runner `/home/acdev/strikes/1663/tools/recording-dock-regression.mjs`: SHA-256 `6f3141c16db4a23699fce84165ea75f9682911f09d714d6d3c9558f65b7cfc2b`; Node syntax check passes. The phone runner adds only failure diagnostics to the desktop runner's assertions.

Accepted PNGs: desktop cases in `recording-dock-verified/`, phone cases in `recording-dock-phone/`. For each width/theme, `timeline-*-playing.png` shows the active halo and Pause dock, `timeline-*-paused.png` shows the cleared halo and Play dock, `dock-*-full-recording.png` shows full playback without an active timeline pin, `dock-*-paused-scroll-hidden.png` shows the intentionally absent island, and `dock-*-playing-scroll-shown.png` shows the reachable island above the report after scrolling. Individual captions are retained in AUT-1663 NOTES.

The finite browser launchers and their contexts have exited; no server/build, provider request, account/data mutation or release was started. This is shared-dev fictional fixture evidence, with source changes by other owners retained, not an immutable release or real-account/production acceptance. Result: expected hidden-state runner failure classified; no product change required.
