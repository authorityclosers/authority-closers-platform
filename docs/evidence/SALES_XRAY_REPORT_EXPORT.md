# Sales Xray report export evidence

The private export is implemented in
`packages/python/ac_platform/conversation_intelligence/report_export.py`. It produces
self-contained Markdown and HTML for an AI draft. The export does not upload
audio, load external assets, or provide a publication route.

Before HTML generation, the exporter checks the original audio SHA-256 against the report,
the transcript source hash and revision against the report, every segment's native integer
time bounds, and every finding quote against its exact segment text and full segment bounds.
The transcript segment count is derived from the supplied list. Timestamps are emitted only
after these checks.

The HTML uses a restrictive CSP: no network connections, images, fonts, frames, workers or
objects; the recording is the only inline data asset. Dynamic report, transcript and quote
text is HTML escaped. Markdown escapes raw HTML and Markdown link/image metacharacters so
untrusted report text remains inert when rendered.

The footer identifies the artifact as a private AI draft. It states that the
draft is awaiting Dipak's sales review and Suyash's measurement/attribution review, that
numeric publication is withheld, and that speaker identity and exact AudioAtlas alignment
remain unverified. This file records implementation evidence only; it contains no private
call transcript or generated report content.

Export validation checks consistency among its supplied inputs; it does not attest
independent source review, human approval, or server-owned checkpoint provenance.
Both formats retain source hash and transcript revision. The generic exporter must
not label an arbitrary parser-valid report as source-reviewed. The actual private
call's coordinator revision has its own external receipt and remains a draft.

Focused evidence command:

```text
$env:PYTHONPATH='packages/python'; pytest -q tests/unit/conversation_intelligence/test_report_export.py
ruff check packages/python/ac_platform/conversation_intelligence/report_export.py tests/unit/conversation_intelligence/test_report_export.py
uv run mypy packages/python/ac_platform/conversation_intelligence/report_export.py tests/unit/conversation_intelligence/test_report_export.py
```
