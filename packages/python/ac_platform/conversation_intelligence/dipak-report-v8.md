# C5 six-pillar Report candidate

Revision: `coaching-v8`. Binding source: Final X-ray Structure, 9 Oct 2026,
`/home/acdev/scratch/specs/final-xray-structure-2026-10-09.md`.
Full document SHA256: `a464e69123f9a649f5f038e464d6086c6d52220b09e3e50eb24b44c6769e3110`.
`dipak_report.REPORT_SECTION_FIELDS` maps every Report section, including the
four deeper analysis groups. Prospect profile and longitudinal Coaching are
separate products; this report returns one follow-up suggestion and one distinct
skill-practice mission.
`pillars.deal.coaching_mission_for` links that mission to the zero-based index of
the `pillars.didnt` card it practises. It is null when no issue fits, and missing
links in older candidate payloads default to null. A link requires a mission and
an existing issue. Coaching uses the issue's own evidence and effect; it does not
guess a match from the mission text.

## Model and saved output

The model returns one compact object: `pillars`, eight `dimensions`,
`summary_evidence`, `sensitive_segments`, `review_status`. The full C2 source
and existing selective C4 evidence remain in the input. It does not generate a
second copy of legacy summary, findings, overview or call map. The server derives
legacy findings from the validated pillars.

Evidence uses direct segment selectors on the model wire. The server resolves
each against the bound C2 source to the actual quote and native timing. Foreign
IDs, invented quotes/dates/timing, invalid chronology and incomplete miss evidence
are refused. Seller/prospect commitments use frozen speaker roles; absent roles
require abstention. An implementation question is not a purchase commitment.
An Important Miss must include seller speech after the prospect opening begins;
seller speech that ended before it cannot establish a chance to respond. Native
overlapping turns and selector order remain valid. A quoted prospect response
must come from prospect-role evidence; deeper response notes must include that
role's evidence, with optional seller context. These checks apply at new-output
admission; existing canonical reads retain their saved-report behavior.
Only people record Won/Lost. Suggestions are distinct from agreed next events.
Skills are observations on this call, with evidence ceilings and no numeric score.

Bounds are maxima, not required filler: 3 worked cards, 3 concerns, 5 moments,
8 timeline phases, 2 commitments per speaker role. Null/empty is valid for
unsupported fields. Plain-language text is short; source quotes retain their
original wording. The local schema bounds output within the existing conservative
24,000-byte ASCII test envelope for 8,000 completion tokens. This is an offline
size check, not a provider token or latency guarantee for every language.

## Browser agreement

B committed the optional `report-pillars/1` parser at `37e0d476`. Account access
projects `content.pillars`, keeping four-field evidence required by the browser.
It preserves the exact legacy `story` shape and the existing guest boundary.
Before/after and timeline keep their source evidence privately in saved C5.
Public deeper analysis uses B's strings/enums. Privacy withholding still applies
recursively; the saved source/report is not rewritten by presentation.

## Activation and timing

V8 remains an offline candidate under the existing AC-SVAL-01 Gate 2 runtime
block. This change does not select it in dev settings, bypass provider/consent
controls, start a paid replay or change payment/access state.

Immediate C1-to-C2 handoff is already implemented by split local/provider runners,
Postgres notifications and immediate due-plan scheduling in the workbench.
A fresh dev-stage export and a measured 20-minute run under 60 seconds remain
required; an old corpus read or unit test is not proof of that target.

## Reproducible checks

- `tests/unit/conversation_intelligence/test_dipak_report_v8.py`: native/provider
  schema, adapters, canonical round trip, role-grounded commitments, timing,
  genuine miss shape, failure cases, account/guest projection, privacy and audit.
- Retained corpus check (private on server):
  `/home/acdev/strikes/1801/check-retained-v8.py`; receipt
  `/home/acdev/strikes/1801/retained-v8-receipt.json` (counts only in notes).
  13 saved reports keep identical admission and canonical content; 14 complete
  C4 inputs prepare V8 with every C2 segment preserved, including one >20-minute
  source. Provider calls: zero. Historical staging data, not current dev replay.
