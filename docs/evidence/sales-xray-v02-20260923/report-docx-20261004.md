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
- App typecheck and lint passed during implementation. Full app checks are recorded in the PR receipt after completion.
- Local live dev checks passed at 390×844 and 1440×900: exact preview/download byte equality, correct filename, all chapters and exact invented quotes, zoom ratios and unchanged download URL, no page-level horizontal overflow, view switching, zero page errors and external requests.
- Browser evidence and the exact generated fictional file: [evidence directory](report-docx-20261004/). The two viewport files have different ZIP timestamps; equality is verified within each preview/download instance.
- The public dev hostname returned Cloudflare Access sign-in. Verification used the existing authorized localhost service on port 3026; no access settings or credentials were changed.

## Native viewer limitations and follow-up

`docx-preview` renders the generated file within browser HTML capabilities. It does not implement all Word field evaluation or automatic overflow pagination; native PAGE/NUMPAGES fields are present in the downloaded DOCX. The in-app preview is the same file, but native viewer pagination and fields can differ. See the [renderer documentation](https://github.com/VolodymyrBaydalka/docxjs).

LibreOffice/soffice and PDF rasterizer tools were unavailable in this run. [AUT-1095](https://paperclip.authorityclosers.com/AUT/issues/AUT-1095), assigned to Root Operator, owns the required LibreOffice → PDF → PNG render and attachments. Word, Google Docs and Pages opening/repair checks are not verified here. Visual follow-up does not gate merge when CI is green, per the current operating rules.

The referenced Windows AC Orchestra skill was not installed in this environment, and no Pro browser connection or existing chat artifacts were available. Local source integration, OOXML tests and browser verification supplied the implementation evidence; no substitute cloud claim was used.

The package manifest and shared lockfile make this a sensitive change: CTO review followed by CEO approval, bound to the PR head. The Lead Engineer does not merge it.
