# AUT-983: generated report DOCX

The existing Document tab now generates a real DOCX in the browser with `docx` 9.8.1 and renders that Blob with `docx-preview` 0.4.1. Its download URL is created from the same Blob. Reading/Tabs retain their mounted panel state; their HTML is hidden during Document mode and is never the document preview or export source.

Scope: one report-document capability, including its generator, view wiring, dependencies and required evidence. This exceeds the usual line target because the task explicitly requires Word styling, generation, preview and contract tests; unrelated refactors are excluded. Source start: `d45dd32` on main. The UI Studio checkpoint `ecb6bd4` preserved the in-progress edits on this task branch.

## Behavior

- A4 pages, 1.9 cm margins, Calibri with Arial display fallback, 10.5 pt body, 15/12 pt headings, navy and gold palette.
- Native Word Title, Heading 1/2, body and numbering styles; bookmarked chapters with page breaks, repeated table headers, rows that do not split, shaded callouts, detailed timestamped evidence, transcript last.
- Supplied findings and observation states only. The score column says `Not scored`; no numeric or official AI scoring is created. Draft and preview boundaries remain visible.
- Header carries the supplied call title; footer contains native PAGE/NUMPAGES fields and Authority Closers.
- Zoom changes the preview's scale; phone width fits the A4 page into the preview region. Zoom never regenerates the file. A failed generation/preview disables download and offers retry. Stale asynchronous results cannot replace another report.
- `/review-fixture/document` opens Document mode by default and remains development-only. Fixture content is invented. No sample report, real recording, provider or customer data was accessed.

## Verification

- 47 targeted tests passed: valid ZIP checksums; every OOXML XML part parses; snapshots of headings, tables and styles; A4/margins; protected rows and repeated headers; native numbering and footer fields; Blob identity for preview/download; zoom reuse; stale generation; recovery; mode/navigation and mounted-state regressions.
- App typecheck, lint and changed-file Prettier checks pass. The browser script also passes Ruff formatting/lint.
- The first complete app suite ran 1,174 tests: four failures comprised two superseded HTML-document assertions (now updated and passing) and two five-second playback timeouts. Those playback assertions pass unchanged with a 15-second local allowance. The corrected complete suite passed with two workers and a 15-second local allowance: 1,168 passed, six skipped. GitHub frontend validation also passed on implementation head `cef2617` with the repository default test settings, including the build. No repository timeout configuration was changed.
- Local live dev checks passed at 390×844 and 1440×900: exact preview/download byte equality, correct filename, all chapters and exact invented quotes, zoom ratios and unchanged download URL, no page-level horizontal overflow, view switching, zero page errors and external requests.
- Browser evidence and the exact generated fictional file: [evidence directory](report-docx-20261004/). The two viewport files have different ZIP timestamps; equality is verified within each preview/download instance.
- The public dev hostname returned Cloudflare Access sign-in. Verification used the existing authorized localhost service on port 3026; no access settings or credentials were changed.

## Native viewer limitations and follow-up

`docx-preview` renders the generated file within browser HTML capabilities. It does not implement all Word field evaluation or automatic overflow pagination; native PAGE/NUMPAGES fields are present in the downloaded DOCX. The in-app preview is the same file, but native viewer pagination and fields can differ. See the [renderer documentation](https://github.com/VolodymyrBaydalka/docxjs).

LibreOffice/soffice and PDF rasterizer tools were unavailable in this run. [AUT-1095](/AUT/issues/AUT-1095), assigned to Root Operator, owns the required LibreOffice → PDF → PNG render and attachments. Word, Google Docs and Pages opening/repair checks are not verified here. Visual follow-up does not gate merge when CI is green, per the current operating rules.

The referenced Windows AC Orchestra skill was not installed in this environment, and no Pro browser connection or existing chat artifacts were available. Local source integration, OOXML tests and browser verification supplied the implementation evidence; no substitute cloud claim was used.

The package manifest and shared lockfile make this a sensitive change: CTO review followed by CEO approval, bound to the PR head. The Lead Engineer does not merge it.

## Initial PR gate (03:15 UTC)

Draft [PR #282](https://github.com/authorityclosers/authority-closers-platform/pull/282), implementation head `cef2617`. `ac-gate check` passes. `ac-gate pr-check 282` reports a file collision with [PR #276](https://github.com/authorityclosers/authority-closers-platform/pull/276), owned by AUT-992: both change `apps/sales-xray-web/app/acquisition-studio.tsx`. AUT-983 adds only the report/transcript source props there. The PR remains draft until that required source file is free and the gate passes. No merge is attempted.

## Continuation (05:25 UTC)

PR #276 merged at 05:04 UTC. The UI Studio checkpoint `f9e21de` already incorporated main through `6573ad1`; the Lead Engineer preserved and pushed that clean checkpoint, reopened PR #282, and confirmed both `ac-gate check` and `ac-gate pr-check 282` pass. The acquisition-studio diff retains only the report/transcript props above.

[AUT-1095](/AUT/issues/AUT-1095) completed the native render of the original fictional DOCX, SHA-256 `0867139e7f1f201f08265a95493afcc28c9388549488854586885420b272ac72`: [seven-page PDF](/api/attachments/49cffb71-f47f-4a73-9fcf-9897c0a72c4d/content), [verification receipt](/api/attachments/05893847-55d4-4de4-8401-be56caea47d2/content), and [every PNG page and support bundle](/api/attachments/423d4627-ce9c-4858-953d-0f4905a9cb28/content). LibreOffice 24.2.7.2 retained all 140 nonempty paragraphs, the invented English and Devanagari quotes, tables and final transcript appendix. Page fields resolved correctly; no clipping, missing glyphs, orphan headings or broken tables were found. Carlito substituted for unavailable Calibri, with Noto Sans Devanagari.

The native render revealed two Analysis paragraphs on an otherwise sparse continuation page. After inspecting that output and the live dev fixture, body after-spacing was reduced from 6 pt to 5 pt and Heading 2 before-spacing from 12 pt to 9 pt. Font sizes, line spacing, A4 dimensions, margins, chapter breaks and report content remain the same. The original evidence above is retained; it does **not** certify the revised pagination.

The revised fixture is in [pagination evidence](report-docx-20261004-pagination/). Its laptop DOCX SHA-256 is `40454fa2608fdd31cfa0455e9efc1d100eadfb76d36b73d2ef2385a7e6e54459`. All 56 targeted DOCX, view, fixture and summary-hook tests pass after the main update and spacing change. Live dev browser checks again pass at 390×844 and 1440×900, including byte equality between preview and download, unchanged Blob on zoom, view switching, zero page errors and zero external requests. Root Operator will rerender this exact revised file through AUT-1095; final native pagination and Word, Google Docs and Pages opening checks remain unverified. Final-head CI is required before the sensitive CTO/CEO review handoff.

## Final pagination verification (06:22 UTC)

The second native render from [AUT-1095](/AUT/issues/AUT-1095) retained one isolated Analysis paragraph on page 5. The fix at generator commit `931350e` reduces body after-spacing to 4 pt and Heading 2 before/after spacing to 6/4 pt. Font sizes, line spacing, margins and report data remain the same. The browser preview also applies the specified Calibri/Arial fallback to generated run styles; its real browser test now checks that fallback.

Final verification passes: 47 targeted OOXML, preview, mode and fixture tests; app lint/typecheck; changed-file Prettier; browser-script Ruff; phone/laptop byte equality, zoom reuse, fonts and view switching. Zero page errors or external requests. GitHub checks on prior head `359734d` all passed; the final PR head must have its own green CI before review/merge.

The final fictional download SHA-256 is `870d97ea9c743892949306a14ee0941755a8fe5f2790c6240ceeadf14282a959`. It was rendered with portable LibreOffice 24.2.7.2 and Poppler 24.02.0, reproduced from the reviewed child-task support scripts using only unprivileged downloads/extraction in run-owned scratch. No packages were installed and no host/service/root changes made. Carlito substitutes for unavailable Calibri; Noto Sans Devanagari supplies the source glyphs. All commands exit 0; nonfatal Java/liblangtag warnings are retained in the evidence bundle.

**Six pages:** cover, Overview, Moments, Analysis, Coaching, transcript appendix. Analysis now fits on page 4, including its previously isolated final paragraph. Native checks retain all 140 nonempty paragraphs, all quotes and every table cell; all table cells stay together on their fixture page; Page 1–6 of 6 fields resolve. Every PNG page was inspected with no clipping, missing glyphs, orphan headings or broken/overlapping tables. The final raster hashes match the inspected pages byte for byte.

Deliverables: [final DOCX](/api/attachments/89da34d4-c4ab-4637-aff4-816630bb9a3a/content), [six-page native PDF](/api/attachments/bf3b855b-1a39-40bd-a710-8c0ed84325c3/content), [receipt](/api/attachments/c56477f2-1bfd-4341-b9c5-75cc668b2874/content), [all files and reproduction scripts](/api/attachments/0141550f-ee64-4286-b782-17f16f684a55/content), [phone](/api/attachments/5a758879-fa6f-4be4-b8a8-e1897322d456/content) and [laptop](/api/attachments/52c4f3e5-50fb-4b61-90ff-7b5efc44a152/content). Each native page is also a separate issue attachment/work product: [page 1](/api/attachments/18bf0cfb-77f1-4691-b1af-e4606a1783ba/content), [page 2](/api/attachments/3fb64e88-f763-4e50-8a9b-2a61c4bc94b5/content), [page 3](/api/attachments/da53c236-abab-474e-aa44-68f0bfdf747d/content), [page 4](/api/attachments/ae1282a6-1c78-4b60-b7a7-1249a844664d/content), [page 5](/api/attachments/f9d77a01-9dab-4423-895b-bc1628418acb/content), [page 6](/api/attachments/a2525fa8-d15a-4a21-9029-5012c05b74e7/content). Machine receipts are in [final evidence](report-docx-20261004-final/). Earlier evidence remains intact and is superseded for final pagination.

Word, Google Docs and Pages opening checks remain unverified. The browser renders the same DOCX bytes, with the renderer's previously documented native pagination/field limits. The sensitive manifest/lockfile review path remains CTO review, then CEO approval; no merge or production/staging change was performed.
