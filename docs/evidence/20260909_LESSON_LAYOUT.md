# Lesson-screen refinement — local working tree

## Implemented

- A reusable, theme-token-based `LessonHeading` keeps the full lesson title and
  accessible player label while reducing the heading's visual weight.
- Video has one 16px phone inset. The native module-path disclosure follows the
  viewer; opening it does not replace the video or change its playback state.
- Up to 900px, video lessons use that disclosure instead of a second course-path
  card below the article. Desktop keeps its course rail; non-video order is unchanged.
- The read-only preview notice remains visible immediately below the picture.
  No media authority, completion rule, enrollment or mutation API was changed.

## Executed checks

- Node 24: **215 existing + 8 presentation tests passed**. Mounted disclosure
  tests retain the actual video element, source, position and speed, with no reload,
  play, Watch, draft or evidence calls. Failed paths suppress stale siblings.
- Full learner TypeScript, scoped ESLint, Prettier and changed-file whitespace checks passed.
- Independent source review: no open Critical/Important finding, including the
  final tablet disclosure change and its shared light/dark styles.
- [Native browser proof](screenshots/native-adaptive-video-2026-09-09T11-35-05-220Z/proof.json):
  **28 checks passed**, including picture input, HLS 360/1080/2160p/Auto, seek,
  fullscreen and player/settings bounds at 320/390/768/1440px. This run preceded
  only the final tablet path-visibility CSS adjustment. Canonical activity state
  was unchanged; its exact newly created tab was confirmed closed.
- Comparable player widths: 320px viewport **240.8 → 272.8px**; 390px
  **311.2 → 343.2px**; 1440px **784.4 → 804.4px**. These are development-layout
  measurements, not loading-speed, smooth-playback or native-device certification.
- [Final layout proof](screenshots/lesson-layout-20260909-lGBdq5/proof.json):
  **8 viewport/theme checks passed**, covering 320/390/768/1440px in light and dark
  with reduced-motion emulation. Each retains one full title, a paused video before
  the module path, and no horizontal overflow. Phone/tablet use the disclosure;
  desktop retains the rail. Native Space-key disclosure interaction preserved the
  mounted player. Root visually inspected light 320px and dark 390px/768px captures.
  Themes were temporary document overrides, not saved account preferences.
  Canonical activity state/revision/actions remained unchanged, no main-document
  write or external-request attempts were observed, and the exact owned tab closed.

## Runtime and release limits

The local processes were authoritatively absent after the environment resumed.
The existing managed launcher restarted the same API/database and all three apps;
previous app logs were copied into a unique local log-archive directory first.
All five ports are loopback-bound. Existing sandbox data was not reset/reseeded.
Chrome was reused, without reading/copying cookies or provisioning accounts.

Chrome's existing test profile and debugging endpoint were rechecked after the
user reported reopening it. All three local app login routes returned HTTP 200;
this does not establish authenticated Admin or Coach sessions.

No Git commit, deployment, DNS/WordPress change or Drive upload is claimed by
this local implementation record.
