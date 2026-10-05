# AUT-1193: unavailable speaker maps

Source base: `88e361eb9f93fce6b32a470884b1b371e29def3c`.

## Contract and change

`speaker_map_service.read_speaker_map` always adds `submission_id`. The GET and
PUT routes in `conversation_submissions.py` set the strong ETag using
`submission_labels.format_revision_etag`: `"call-label-<user_revision>"`.
Those client checks match the current server and remain enforced.

`speaker_map.predict_speaker_map(None)` returns `status: "unavailable"`,
`unavailable_reason: "transcript_not_ready"`, `transcript_revision: null`,
`map_revision: null`, `report_basis: null` and `speakers: []`. The client rejected
both the null revision and the empty list. A retained transcript with no speaker
IDs can also produce an empty predicted map. These are now accepted as an absent
map, with a quiet “Speaker names not set yet.” message and the shared app button
for retry. A later populated response removes the message and enables the existing
speaker editor. No fabricated speaker roles or unavailable-map saves are allowed.

Populated maps still require the report's exact transcript revision. Predictions
prefill the editor; only confirmed/channel roles feed role-specific measurements.
Submission binding, ETags, confirmed PUT acknowledgements and save errors remain
enforced. `map_revision` and `report_basis` are server provenance metadata, not
substitutes for these bindings. This repair changes no server or stored data.

## Verification

- The two absent-map regressions failed before the fix; the focused provider,
  profiles and call-map suite then passed all 44 tests.
- Tests cover unavailable/null revision, empty prediction, ready-after-retry,
  confirmed display/edit/save, predicted role isolation, and rejecting mismatched
  submission, populated-map transcript revision and ETag.
- Web lint and typecheck passed; lane check and diff whitespace check passed.
- Prettier passed for every changed source and evidence file.
- The default full app run reported the upload-navigation test timeout and was
  terminated before a final suite result. A bounded two-worker run also reported
  that test timing out at the default 5-second limit. Its isolated rerun with a
  20-second ceiling passed (test body: 1.79 seconds). The same timeout is recorded
  in the earlier AUT-992 speaker-browser-wiring evidence. This is not a claim
  that the full default app suite is green.
- Browser: actual branch components with fictional mocked responses at 390 and
  1440 px, for unavailable, predicted and confirmed maps. Call map visible, no
  alert banner, no horizontal overflow or page errors; populated maps open the
  existing editor, and the confirmed map opens the talk-share view.
- [Browser receipt](browser-checks.json); [unavailable phone](unavailable-390.png),
  [unavailable laptop](unavailable-1440.png), [prediction phone](predicted-390.png),
  [prediction laptop](predicted-1440.png), [confirmed phone](confirmed-390.png),
  [confirmed laptop](confirmed-1440.png).

## Dev check and limits

The running loopback dev report preview was checked before editing at both widths:
no overflow. Public https://salesxray-dev.authorityclosers.com redirects to access
sign-in. The screenshots prove local components and contract handling, not the
authenticated Tester report or staging response body. No real call, recording,
provider, account write, merge or deployment was used. The temporary harness was
stopped and removed.

After the change is visible on dev, open the Tester report and an older fictional
claimed call. An unavailable/empty map should show the quiet message and the call
map, without the previous banner. Reload speaker details after the map is ready;
open a speaker chip, confirm names/roles, save, and reload. Check predicted and
confirmed calls at phone and laptop widths. Confirmed roles should retain their
talk-share view. Repeat on staging after the release train deploys the merge.
