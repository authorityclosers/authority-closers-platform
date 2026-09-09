# Player delivery renewal — localhost acceptance

Existing dirty `d2de` tree, HEAD `2c56de938753a669265c4dda0d08ad9f3cb2ed0b`.
No commit, push, staging/production deployment, or Drive release publication.
Only the managed local API was restarted (PID 6176); learner 3100, admin 3101,
database, accounts, uploaded portrait and existing attempts were preserved.

## Implemented

- Normal authenticated activity reads rotate expiring delivery grants; scope,
  original TTL, immutable predecessors and atomic audit remain server-owned.
  See [backend evidence](20260908_MEDIA_DELIVERY_RENEWAL.md).
- A strict comparison helper pins learner/tenant/session, enrollment, content,
  binding, rendition/caption objects and playback mode separately from grant
  generation. Re-signing one grant does not reload the player.
- Bounded pre-expiry refresh keeps the viewer and existing canonical watch
  session mounted. Position, pause intent, rate, quality, volume and captions
  survive replacement. Explicit controls during reload update pending intent.
  Denial, changed scope and old-grant expiry still stop unauthorized playback.
- Late canonical responses use the latest installed delivery deadline; repeated
  concurrent responses do not install one successor twice. Offline recovery
  retains a still-valid watch session. Expired/invalid evidence sessions require
  explicit restart from zero, not invented continuity at a restored offset.

## Passed verification

Final six-suite player run: **316 tests**, including 29 mounted adaptive cases,
89 identity cases and existing loader/decoder/playback regressions. Full learner
TypeScript, scoped ESLint, formatting and script syntax checks passed. Backend:
460 broad regressions, 82 overlapping focused cases, two real PostgreSQL cases,
full Python mypy. Independent scoped review has no open Critical/Important issue.

[Real-time renewal proof](screenshots/native-adaptive-video-2026-09-07T22-29-27-346Z/proof.json):
**25 checks**, real Chrome native mouse/keyboard input, new signed-in synthetic
learner tab. No clock change, fabricated token or harness activity refresh during
the wait. One successor was observed; old manifest returned **403** after expiry.
Paused position remained **1.096735s**, rate **1.5x**, muted, captions hidden.
Playback subsequently decoded 360p, 1080p and genuine 3840x2160 frames.
Activity revision/actions unchanged; zero observed main-document mutation or
external-request attempts. Before/after and 320/390/1440 screenshots are saved
in that directory; root inspected desktop renewal and 320px settings captures.

Review then corrected saved-position Skip +/-10 during reload; its regression
passes. The final-code [native regression](screenshots/native-adaptive-video-2026-09-07T22-34-14-371Z/proof.json)
passed **23 checks**, retaining mobile fit and 4K decoding. It leaves its owned
Chrome tab paused; existing user tabs were not selected or closed.

## Limits

The film is a 12-second openly licensed technical fixture, not Dipak teaching
content. Grant counts observe attempted masters; buffered frames alone do not
prove fresh post-expiry segment bytes or uninterrupted long-film streaming.
Actual continuous long-film renewal, native progressive renewal, Safari HLS,
bandwidth-driven Auto adaptation, live revocation and tracked browser completion
remain unverified. Frame drops occurred during switching; this is not a smoothness
or performance-budget pass. Local films still have no completion policy.

Final viewer SHA256: `BB6D6C527F43A68DB1464010D688B90054E4F13E53D53B37413DF15A684F50BC`.
