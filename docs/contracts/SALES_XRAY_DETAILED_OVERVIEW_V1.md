# Dipak overview v1 — implemented report contract

This is an implementation contract, not a replacement for controlled AC scoring,
privacy, provider or release approval. The owner supplied `REPORT-Detailed 14 points.pdf`
as the presentation reference. Its ten pages have SHA-256
`4fad19ce3234848c9f992190f9f498184bb8be6996664a9e7cb6dc133aa3a0eb`.
Its example timestamps, XX placeholders and illustrative outcomes are not call data.

The existing source-bound report may now contain `overview`, with version
`dipak-14-point-v1`. Absence preserves historical report serialization. Presence
requires every v1 key, including explicit nulls and empty arrays for missingness.
The authoritative typed schema is `report_overview.py`; the browser's strict
decoder is `overview-contract.ts`. A shared synthetic fixture passes both.

| Reference part | Implemented data and user presentation |
| --- | --- |
| Header | Source duration stays in the existing player; optional source-linked diagnosis and draft observed outcome. No inferred closer identity, level or score. |
| 1 Strengths | Existing up-to-three findings plus why each matters. |
| 2–4 Priority fixes | References to the existing ordered improvements; separate source-linked observation, reason, replacement behavior and business-impact missing inputs. No filler to reach three. |
| 5 Golden moments | Explicit selected strength/evidence references and why effective. No duplicate or out-of-range references. Legacy view is labeled as saved strengths, not a new assessment. |
| 6 Missed opportunities | Prospect signal, closer response, possible follow-up and possible impact, bound to source quotations. |
| 7 Possible meaning | Quoted source beside possible concern; always labeled inference. |
| 8 Rewatch | Up to three distinct source spans with must-watch/watch/repeat purposes. Legacy view offers one distinct clip per existing finding category. |
| 9 First meaningful change | Before/change/after source notes in chronological order, with possible effect explicitly labeled inference. Null means not established. |
| 10 Skill review | Eight existing qualitative dimensions and optional source-linked ethics observations. No ethics pass/fail, overall grade or invented extra five points. |
| 11 Next-call focus | Exactly one behavior and observable target, referencing improvement zero. |
| 12 Practice | One drill and success condition tied to that same improvement. Legacy reports do not receive an invented personalized drill. |
| 13 Progress | Null and hidden: the single-call C5 input contains no comparable historical calls. A changed judge is not evidence of learner improvement. |
| 14 Verdict | Separate repeat/fix-first/next-focus/assessment fields. Remains an unadjudicated draft. |

Every newly supplied evidence object must name an existing transcript segment,
contain a literal substring of its text and match the original whole-segment
timestamps. The backend derives source hash and transcript revision. The browser
rechecks those bindings before presentation; React renders all prose as text.
Unknown fields, invalid references, duplicate rewatch spans, nonchronological
changes, numeric publication fields and invented financial/history structures fail.
Structural validation cannot prove coaching quality or causal truth; the human
review and calibration gates continue to apply.

Business-impact status is currently only `insufficient_data`, with named missing
inputs. The source weights remain 95 against declared 100. No numeric normalization
or publication approval is inferred from this template.

## Checkpoints and provider bounds

New C5 inputs include `REPORT_FORMAT: dipak-14-point-v1` and its required semantic
shape before the trailing, broker-validated Profile JSON. Their input hash changes,
so a new coaching result is required; C2 transcription and C4 facts remain reusable.
The old report stays readable. A response to the new marker must include the
overview and cannot silently succeed as the legacy broad report.

The HTTP selection and durable processing-plan paths use the same output allocator:
C4 stays at up to 1,400 tokens; C5 can use up to 3,200, always at or below the exact
approved stage maximum. The existing input-plus-output 8,000 TPM preflight remains.
No allowance, quote price, privacy consent, request count or budget cap is raised.
The model is told to omit redundant server-owned metadata. Real-provider output
completeness and quality at a given approved limit still require provider testing.

## Integration boundary

Standalone and embedded LMS CallStudio mount this same overview. English controls
preserve original mixed-script content. Keyboard-operable details, source seeking,
320/390/1280 layouts and before/after-print restoration are covered.

The acquisition `report-access/2` projection must explicitly include the optional
already validated overview for the current report owner. This packet does not
mount guest HTTP or invent guest identities. The acquisition-to-worker adapter is
separate work. Existing authenticated intake/analysis/processing-plan APIs and
workers remain the processing foundation. Hosted activation, provider readiness,
authenticated live smoke and release promotion require their own receipts.
