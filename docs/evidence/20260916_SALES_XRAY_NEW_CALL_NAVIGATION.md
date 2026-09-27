# Sales Xray — explicit new-call navigation

Base: `c95b35c474293abeae16d55f63bf1c825f8f7126`, 2026-09-16.

## Bounded correction

Desktop/sidebar and mobile Analyse links now use explicit `?new=1` intent and
native document navigation. Plain `/` previously reopened the remembered call;
same-route client navigation could also retain the mounted restored-call state.

New-call entry skips the remembered selector without deleting it, cancelling a
call or changing saved processing. Explicit valid `?call=…` links still restore
their call and take precedence over a stale new-call flag. Error states with no
parsed submission now offer **Analyse another call**. That action preserves the
selector, marks new-call intent, resets local display state and rechecks entry
and session using read-only requests. Refresh remains on the new upload screen.

The marker is consumed only when the next upload attempt records its own opaque
selector, so refresh can recover that attempt normally. Bootstrap snapshots its
navigation intent before any await: independent review found and we fixed a race
where a quick new upload during a delayed entry read could otherwise be mistaken
for old saved work. No API, parser, processing, quote, restore-policy or consent
contract changes; saved-call ownership checks remain server-authoritative.

## Evidence

- Node24 production build/TypeScript and ESLint pass.
- Frontend suite: **274/274 tests**, 28 files, two workers.
- Independent follow-up review: **53/53 focused tests**, no remaining P0–P2.
- Exact final compiled candidate at loopback3119, Chromium, synthetic APIs only:
  desktop1024×626, phones390×844 and375×667. All three pass native Analyse
  navigation, new-entry reload, generic-error escape, retained opaque selector,
  explicit saved-call restoration, zero API mutations and zero browser errors.
- Recovery action fully inside each viewport. Final phone error and desktop new
  entry screenshots visually inspected. Phone error recovery is clear; the
  existing decorative uploader steps remain crowded below it. This patch does
  not redesign that approved layout.
- A preliminary browser assertion counted Next's empty route-announcer as an
  app error; the final script scopes error assertions to the actual workspace.

[Browser records](sales-xray-new-call-navigation-20260916/results.json)
and screenshots accompany this document. This is local compiled/fixture evidence,
not a real public-call or fresh-upload pipeline claim. Release coordinator owns
merge, deployment and actual public verification.
