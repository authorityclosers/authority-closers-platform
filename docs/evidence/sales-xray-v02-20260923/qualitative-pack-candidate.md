# Versioned qualitative prompt candidate

Local implementation on 23 September 2026; not activated in production.

The first-release product decision from the authorized
[Pro research conversation](https://chatgpt.com/c/6ab28423-da78-83e8-bf61-9cda0bbf5678)
was checked against captured Brain 2.0, Brain 2.1 and September 22 context sources.
The ten-rule single-call pack records exact Drive IDs, captured-text hashes and
section references. Numeric scoring, entitlements and admission remain outside it.
The source register records candidate status, not automatic policy activation.

`coaching-v4` explicitly requires the packaged rule hash and supports English,
Hindi + English and Marathi + English generated prose. Native source text and
wire identifiers stay unchanged. Historical v1–v3 prompt bytes remain identical
for a frozen fixture; passing new language/pack options to them is rejected.
Language changes create a distinct prepared-input digest. The broker's trailing
approved-profile JSON contract is preserved.

Validation: 75 unit checks passed across the pack, prompt, report and inference
adapter suites. Ruff and targeted mypy passed. These verify contracts, source
integrity and backward compatibility; they do not establish generated-report
accuracy, multilingual fluency, or provider performance.

Remaining integration: freeze selection into versioned Admin/CLI settings and
accepted processing plans, checkpoint/recovery provenance, expose report-language
selection and compatible report views, and complete synthetic semantic review,
staging and production acceptance. Loading the pack alone does not activate it.
