# AUT-992 E0.3b: server-backed speaker editor

Base: `9292bce58b81a2047584c5e7f3c65f14efbda420`. Uses the speaker-map contract merged in PR #271, under ADR 0042.

Claimed, signed-in reports now mount a speaker provider keyed by call, transcript, person, session and workspace. Every report consumer reads the server projection; predictions prefill confirmation but do not become confirmed measurement roles. The editor shows the full role list and sends one conditional PUT on Save, including the chosen icon. Pending saves disable repeat confirmation. Failed saves retain the draft; 409 refreshes the ETag and requires another explicit Save. Call/session changes abort pending reads and writes and ignore late responses.

Legacy speaker storage prefills an unsaved editor only before the first server revision. It is removed after an acknowledged save, confirmed logout or successful deletion. Live guest reports cannot use local profiles or edit them. Standalone development fixtures retain their local demonstration store. The speaker editor's local-save caption is removed. Key-facts and promise ticks, including their separate caption, remain for AUT-430/AUT-431; this is not completion of the entire saved-on-device requirement.

## Verification

- Lint, typecheck, Prettier and lane check passed.
- Changed-area web suite (eight files): 195 passed, one existing upload-navigation test timed out. That test passed on its isolated rerun. Speaker regression rerun: 42 passed; final persistence suite after adding the unresolved-third-speaker case: 7 passed.
- Persistence tests cover acknowledgement before display, no picker/cancel write, full speaker list and ETag, fresh-session reads, legacy prefill/removal, prediction isolation, conflicts, failed/malformed responses, late writes after logout, logout cleanup and unresolved roles.
- Browser: actual branch CallMap, SpeakerEditor, provider and ReportTranscript with application CSS in a temporary local component harness, at 390×844 and 1440×900. Cancel makes no PUT; 503 retains the draft; retry persists; a fresh browser reads the name and icon; no local speaker storage write, no speaker local-save caption, no page errors or horizontal overflow. Harness processes were stopped.
- [Phone](speaker-server-390.png), [laptop](speaker-server-1440.png), [browser receipt](speaker-server-browser.json). The receipt contains only fictional payloads and records the two attempted PUTs (failure, then retry).

## Dev and staging check

On https://salesxray-dev.authorityclosers.com, sign in to a sandbox account and open a fictional claimed call. At 390 px and laptop width, edit a speaker name/role/icon, inspect the full role list, then Save. Reload and use a second signed-in browser to verify persistence and consistent names across the map and transcript. Confirm Cancel and picker clicks send no PUT. Simulate a failed PUT or stale ETag: the editor must retain the draft and allow an explicit retry. Verify confirmed logout removes legacy `ac.xray.speakers.v1:*` keys. Repeat on staging after the release train deploys the merged change.

Limits: screenshots prove components with fictional mocked API reads/writes, not deployed persistence. No real account, recording or provider was used. The current loopback dev fixture was checked before editing: it still showed the local-save caption and older Transcript icons; its live checkout belongs to the UI lane and was left untouched. Public dev sign-in, authenticated dev writes and staging verification remain unverified. No merge or deployment was performed. Keep E0 open for the remaining slices.
