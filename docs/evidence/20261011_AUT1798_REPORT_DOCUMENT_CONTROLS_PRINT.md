# AUT-1798 — Document controls and clean printing

The Report's Document contents links and clip buttons now meet the shared
control sizes: 32 px on desktop and 44 px on touch. The summary's accessible
name comes from `END_SUMMARY.title` in the Report copy module. Printing keeps
compact contents and timestamps and disables motion while the shell is hidden.
Its search form and account control no longer paint over the call facts.

## Changes

- `8dc4d07d`: clip controls were 24 px and contents links 16 px; both now use
  `--sx-control-h`. The summary region and table use the existing copy key.
- `d8358066`: print-only motion rules in `report-document.module.css` clear the
  two shell control shapes. No shell component or shared stylesheet was edited.

## Verification

- Document page, model and Word suites: **29/29 pass**, including a repeat after
  B's shared-model corrections at `09a60321`.
- Incremental TypeScript check and focused cached ESLint: pass before the
  TypeScript commit. Diff checks and shared dev route HTTP 200: pass.
- Shared dev, 1440/390 px, light/dark: **4/4 pairs pass**, 40 clip/contents
  targets per pair reach 32/44 px; no runtime errors or sheet/viewport overflow.
- Four Word downloads: ZIP checksums and every XML part valid; six headings
  and eight short skill names appear in order.
- Post-print-fix screen and print matrix: **4/4 pairs pass**. All six Document
  headings remain; hidden shell controls have transition 0s / animation none.
  Clean first-page print and phone dark screenshot inspected.
- Retained corpus: 13 finished reports (11 real/presumed, two fictional), three
  entries without a report; 13 Document renders, zero failures/provider calls.
  Existing generated prose still contains 36 analyst-word occurrences in 11
  reports. That count is unchanged; this UI change does not rewrite saved prose.

Receipts and fictional screenshots remain on the AC server outside Git:

- `/home/acdev/strikes/1798/shots/2026-10-11-document-controls-2248/receipt.json`
  (stable head `fc769f2c`; four Word files).
- `/home/acdev/strikes/1798/shots/2026-10-11-document-print-fixed-2258/receipt.json`
  (heads `09a60321` → `f380e35d`; four screen PNGs, four print PNGs and PDF).
  Document CSS SHA256 stayed
  `613a196abf231a85e2cb15edbe0e551c54ef26463d101db02f233b87c326ccec`.

## Check on dev

Open `http://127.0.0.1:3026/review-fixture/report/story`, choose More views →
Document, then Print or save as PDF / Download Word file. Contents links and
clip buttons use the larger hit areas; paper shows times without Play controls.

Browser evidence here uses the fictional fixture. E owns authenticated deployed
readback with existing QA sessions. The coordinator owns versioning and shipping.


## QA retained phone/light print capture, 23:34 UTC follow-up

E's 23:29:54–23:31:27 run passes all 12 automated cases, including four
full-shell print checks. QA inspected all A4 captures and confirms the old
shell-control shapes are gone. Its 793×1122 phone/light PNG raises a separate
right-edge clipping question; actual PDF clipping and the cause are unproved.

G inspected the exact saved PNG and read the exact retained PDF locally:
`1694/shots/2026-10-11-workbench-coaching-font-quote-readback/document-print-390-light.pdf`,
SHA-256 `eb84a508b316e59906e14c6b8cce5369864e2573ec5c7ec955374eb623345c83`.
A bounded standard-library PDF stream/ToUnicode text read found 11 pages
and the complete "Friday at 4:00 PM." text. Text presence alone does not
prove pixel bounds or absence of clipping.

No PDF rasterizer is installed in the system or repository venv. The existing
full Chromium native viewer cannot launch because `libcups.so.2` is missing;
its finite process exited before rendering. No package was installed, new
app visit made for this classification, or substitute PDF generated. Retained
text-only receipt: `1798/shots/2026-10-11/document-print-pdf-2337/text-only-receipt.json`.

The capture cause and actual PDF pixel bounds remain **unproved**. E's already
scheduled 23:44:55 wave owns original mobile visual-viewport/sheet geometry.
No speculative print CSS change or new broad browser wave by G. The earlier
print repair's source/automated/inspected evidence remains separately scoped.
