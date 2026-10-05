# AUT-1003 phone parity audit — 4 October 2026

Source: `task/ui/1003-phone-parity`, continuing `c1debfa`; browser: headless Chromium, reduced motion. Actual dev web server: `http://127.0.0.1:3026/review-fixture/shell`. Hosted dev did not expose the fixture in this browser session; a direct request returned 403. The fixture is development-only, explicitly fictional, and mounts the actual shell and report components. All `/v1/` requests were intercepted; non-origin network traffic was blocked. No real account, recording, provider or database mutation was used.

The phone shell offers Dashboard, New analysis, Calls and Account; the development banner adds Settings. Prospects and Analytics routes do not exist at this source pin. Top safe-area spacing is included. The report keeps its own 16 px reading margin and no longer adds the shell's second margin.

| Viewport   | Report width | Shell side padding | Horizontal overflow / page errors |
| ---------- | ------------ | ------------------ | --------------------------------- |
| 360 × 800  | 328 px       | 0 px               | none                              |
| 390 × 844  | 358 px       | 0 px               | none                              |
| 430 × 932  | 398 px       | 0 px               | none                              |
| 1440 × 900 | 984 px       | 48 px              | none                              |

92 screenshots cover reading section starts/ends, every tab's starts/ends, the transcript reader, all generated DOCX chapters, and the shell. [Machine proof](browser-proof.json) records widths, scroll widths, zero page errors and 26 intercepted GET requests. Automated checks also verify phone navigation, active Dashboard state, 44 px touch targets and document/reader horizontal fit. They do not prove that a DOCX chapter heading stays uncovered after navigation settles.

| Section    | Tab at 360 / 390 / 430 px                                                                     | Document at 360 / 390 / 430 px                                                                               |
| ---------- | --------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| Overview   | [360](tab-overview-360.png) / [390](tab-overview-390.png) / [430](tab-overview-430.png)       | [360](document-overview-360.png) / [390](document-overview-390.png) / [430](document-overview-430.png)       |
| Transcript | [360](tab-transcript-360.png) / [390](tab-transcript-390.png) / [430](tab-transcript-430.png) | [360](document-transcript-360.png) / [390](document-transcript-390.png) / [430](document-transcript-430.png) |
| Moments    | [360](tab-moments-360.png) / [390](tab-moments-390.png) / [430](tab-moments-430.png)          | [360](document-moments-360.png) / [390](document-moments-390.png) / [430](document-moments-430.png)          |
| Analysis   | [360](tab-analysis-360.png) / [390](tab-analysis-390.png) / [430](tab-analysis-430.png)       | [360](document-analysis-360.png) / [390](document-analysis-390.png) / [430](document-analysis-430.png)       |
| Coaching   | [360](tab-coaching-360.png) / [390](tab-coaching-390.png) / [430](tab-coaching-430.png)       | [360](document-coaching-360.png) / [390](document-coaching-390.png) / [430](document-coaching-430.png)       |

Reading screenshots use `<section>-<width>.png`; lower-content captures use `<section>-end-<width>.png` and `tab-<section>-end-<width>.png`. Reading omits the transcript by the existing design; Document includes it as an appendix. Header reader evidence: [360](transcript-reader-360.png), [390](transcript-reader-390.png), [430](transcript-reader-430.png). Laptop reference: [shell](shell-1440.png) and [Overview](tab-overview-1440.png).

Visual review: standard report text, cards and controls fit the phone viewport. Long section navigation intentionally scrolls horizontally; All report sections offers every destination. Document mode preserves the existing A4 page fit, so text remains small at 100% on a phone. Two existing issues were recorded in the Intake Ledger: [AUT-1166](/AUT/issues/AUT-1166), [AUT-1167](/AUT/issues/AUT-1167). Findings: Devanagari excerpts show missing glyphs in the DOCX preview; some DOCX chapter jumps leave their headings above the toolbar. No report navigation or font source was changed here.

Validation: `ac-gate check`, web typecheck, lint and changed-file Prettier pass. The focused shell/fixture run passes 5 tests (2 files). Ruff format/check passes for the browser audit. The complete web test command reported two acquisition test failures and later ended with SIGTERM; a selected rerun reported 25 passed, including those scenarios, but also received SIGTERM after its summary. Full-suite completion is unverified; CI must pass before merge.

Reproduce: `SALES_XRAY_BASE_URL=http://127.0.0.1:3026 SALES_XRAY_UX_EVIDENCE_DIR=<output> uv run python apps/sales-xray-web/tests/browser_phone_parity.py`. On hosted dev with existing access, open `/review-fixture/shell`, use 360/390/430 px, check Dashboard/New/Calls/Account, choose each section in Reading, Tabs and Document, and open Transcript. Do not use real calls. Physical iOS/Android devices, native permissions, authenticated workspace switching, staging and production are unverified. The wrapper plan and CEO options live in the task's `plan` document.
