# AUT-1677 — Report citation reads and full-call Coaching link

Source base: main `5a48d39` (watchdog merge of #439). Controlled binding spec:
`final-xray-structure-2026-10-09.md`, SHA256
`a464e69123f9a649f5f038e464d6086c6d52220b09e3e50eb24b44c6769e3110`.

Report Coaching offers **Open full coaching for this call** at the source-checked
`/coaching?call=<submission_id>` destination, alongside across-call Coaching.
The retained report fallback exposes the call link only in the current signed-in
workspace. Withheld or unavailable authorised evidence keeps its existing
unavailable state. The links disable prefetch.

Canonical Report parsing builds the controlled profile's citation index once
per parse and reuses it for the eight dimension and nine section checks. Each
citation still requires its dimension/section-specific scope. A later parse
builds a fresh index from its own profile. Report admission/adaptation semantics
and validator `/10` are unchanged; the reviewed source-hash assertion now pins
`943140feb100431af3cb9f0b5904a561db72d4aec0ad34927bd55931a5c86433`.
Recording, receipt, report, transcript and profile hashes, canonical provenance,
current erasure and effective withholding continue through the existing reads.

## Focused verification

- All 90 `test_reports.py` cases pass, including numeric-key refusal, native
  evidence, older report formats, the fresh-profile boundary and rejection of
  supported citations borrowed from the wrong dimension/section.
- Strict module mypy and changed-file Ruff pass.
- All 56 Report Coaching read/codec/view cases pass; app typecheck and changed
  ESLint/Prettier pass.
- Fictional browser proof passes at 390 and 1440 pixels in light/dark themes:
  exact call-link destination, source/lesson rendering, explicit media play and
  retry, Devanagari transcript, 44px phone links/controls, no overflow or page
  errors, zero bootstrap API reads and zero external requests. Screenshots were
  inspected. The temporary preview stopped and generated `next-env.d.ts` was
  restored from the source base.

The synthetic comparison uses the exact `7995d9c` parser and candidate on the
same canonical eight-dimension/nine-section fixture. Canonical output hashes
match (`d367c3fce893ba63f50ffe0b9605eb5616a877f1f9b171347603376361f2defc`).
Profile scans per parse fall from 17 to one. Five batches of ten parses had local
median times of 9.210ms before and 1.780ms after. Host timing varies; this is an
offline synthetic measurement, not a production timing or acceptance receipt.
The count-only benchmark receipt is retained in the strike folder.

Retained native-source follow-up on `21964af`: both the exact `7995d9c` parser
and candidate admit all 13 retained corpus C5 reports against their original C2.
All 13 canonical output hashes match; three C5s are absent and zero provider
calls occur. The opt-in account/guest projection, six-pillar, Word and Coaching
corpus test also passes on this source. Inputs and receipts remain private on
the AC server; this comparison carries no hosted ownership or quality claim.

## Check after the normal merge and dev refresh

Open a finished call, select Coaching and follow **Open full coaching for this
call**. It should open that submission's Coaching page; the separate across-call
link remains. Older Reports keep their views/defaults and honest missing fields.
Authenticated hosted verification remains with H/QA. A still owns the saved-call
route/studio adoption of the prepared server preload; this change does not claim
that route integration or a production deployment.

## Shared-dev integration follow-up

After main `d2c2caa` was integrated as `d986c9e`, the focused Report/Company
integration passes 175 frontend cases and incremental typecheck/lint/format.
The actual retained account/guest/pillar/Word/Coaching corpus proof passes again
on `22765f8`, after the main Coaching component changes, with zero providers.

The shared `dev/live` journey exposed 40px clip retry and 32px slide controls at
390px inside Report. Report's existing scoped control rule now also covers
nested buttons, with a 44px height/width floor on phone widths. No Coaching-owned
file, shared token, raw colour or permission changes. The browser proof checks
visible controls in a touch-enabled phone context, explicit play/retry and
transcript/slide interaction. Screenshots come from the existing shared server
at `http://127.0.0.1:3026`; no private preview or local build is started. Final
receipts, source pin and individual image observations are recorded in strike
NOTES.md and `shots/2026-10-11/`, after the committed-work refresh.
