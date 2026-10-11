# AUT-1801: phone audio intake

Source pin: `a5c71f8` plus AUT-1608 source commit
`c25865eb0561b5321ac6d5ffa571530d3c20ab2b`, absorbed as `1a067b6`.
The old remote branch was already absent when checked; no unrelated branch was deleted.

The picker and client validators now agree on AMR, AMR-WB, AAC, 3GA,
WebM/Opus and Ogg/Opus alongside the existing formats. The backend detects
the container from bytes, preserves the original content hash and uses
decoded duration for admission. A filename or supplied MIME type alone
does not certify valid media. Existing size, consent and retention checks apply.

The test fixtures are generated tones/artificial AMR frames, not customer
audio. Focused media tests passed (56 passes; 16 numerical native tests
skipped in that initial unit invocation). Both phone-format PostgreSQL HTTP
cases passed with the native executable built inside the test fixture.
They exercise real hosted upload preflight and local processing, with no
provider calls. The three touched web suites passed: 149 tests; the final
file-stage rerun passed all 11 tests.

After building the pinned native executable locally through the heavy slot,
the phone media, signal, canary atomicity and known-fixture checks passed all
75 tests without skips. Initial canary atomicity failures disappeared with
the required executable present; no production code or shared test fixture
was weakened to make them pass.

ESLint, TypeScript, the final focused Prettier check and a production
`next build` passed. The temporary
`next start` browser check uses local fictional sandbox responses and an
actual selected AMR fixture. It checks phone/desktop widths, light/dark
theme, visible selection, no page errors and no horizontal overflow.
The operator inspected all four screenshots before pushing.

Private screenshot and receipt directory:
`/home/acdev/strikes/1801/shots/2026-10-11/`.
Filenames are `phone-upload-1440-light.png`, `phone-upload-1440-dark.png`,
`phone-upload-390-light.png` and `phone-upload-390-dark.png`.
This proves the production-built local UI, not a production upload or
external-provider compatibility certification.
