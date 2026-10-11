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

## Check after the normal merge and dev refresh

Open a finished call, select Coaching and follow **Open full coaching for this
call**. It should open that submission's Coaching page; the separate across-call
link remains. Older Reports keep their views/defaults and honest missing fields.
Authenticated hosted verification remains with H/QA. A still owns the saved-call
route/studio adoption of the prepared server preload; this change does not claim
that route integration or a production deployment.
