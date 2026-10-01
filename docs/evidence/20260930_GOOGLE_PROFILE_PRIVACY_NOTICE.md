# Approved Google-profile privacy notice

## Authority and scope

[AUT-638](/AUT/issues/AUT-638#document-plan) carries the approved scope from
[AUT-391](/AUT/issues/AUT-391): append the exact Google-profile sentence to
“Account information and its purpose”, publish version
`ac-learner-terms-privacy-2026-09-30-v1`, effective 30 September 2026, and move
matching release pins together. The September 13 evidence remains unchanged.
The existing checkbox, consent refusal rules and audit history are preserved.

The policy exports feed `/privacy`, `/terms` and registration. Both checked-in
release profiles and the installer's reviewed-version literal match those
exports. Current configuration references and rendered/browser assertions use
the new version. Parser tests retain missing/unreviewed refusals and add the
September 13 version as stale for both profiles. Only approved files changed.

## Recovery packet

[ac-learner-terms-privacy-2026-09-30-v1.json](/api/attachments/bb97fc08-21db-4a13-88ee-b7a5f3e690a7/content)
was serialized directly from the published TypeScript exports with Node 24.19.0.
It contains version, effective date, contact, the complete joined checkbox text,
and both ordered policy arrays, with two-space indentation and a final newline.

- UTF-8 bytes: **13,353**.
- SHA-256: `5f8d288288c076af751bbe15095620618e2d2d0a42ea6b8852ba65a205458016`.
- Attachment: `bb97fc08-21db-4a13-88ee-b7a5f3e690a7`.
- Artifact work product: `fa9cbf16-438d-4d44-9896-dcf715391d5f`.

## Validation and deployed proof

- Release tests: `uv run pytest tests/infra/test_application_release.py` exited 0;
  97 passed, one skipped because no Docker daemon is available. The extracted
  parser accepts current pins and refuses missing/stale/unreviewed pins before
  deployment effects, with the expected consent-variable diagnostics.
- `pnpm --filter @ac/learner-web test -- app/lib/learner-ui.test.ts` exited 0:
  1,803 tests passed across 112 files (the argument form ran the whole suite).
  Direct focused execution with `pnpm --filter @ac/learner-web exec vitest run
  app/lib/learner-ui.test.ts` also exited 0: 89 tests passed.
- The uploaded recovery bytes were read back and matched the recorded SHA-256.
- Changed-file Ruff format/check, Prettier and installer Bash syntax passed.
- A byte comparison with the base policy confirms that only the version, date
  and exact approved sentence changed; recovery JSON format was verified.
- The admin continuation gate passed on this task branch.

On 1 October 2026, read-only Chromium inspection of dev `/privacy`, `/terms`
and `/register` reached the Cloudflare Access sign-in page. The policy panels
and signup version were unavailable. Browser verification against dev is a
follow-up after access and merge; no provider call or account creation occurred.
The two existing browser files use same-origin reads and intercepted Google
start requests. CI owns its existing isolated registration browser gate.

PR: [#173](https://github.com/authorityclosers/authority-closers-platform/pull/173).
Final CI, merge SHA and post-merge dev proof remain pending and will be recorded on
[AUT-638](/AUT/issues/AUT-638) for the existing [AUT-634](/AUT/issues/AUT-634)
release-candidate check. No staging/production access or promotion occurred.
