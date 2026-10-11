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
