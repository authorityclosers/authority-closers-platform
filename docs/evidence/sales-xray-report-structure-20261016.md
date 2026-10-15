# New Report data contract — 27 pointers, 16 October 2026

Source: owner's 03:05/04:00 IST instructions in AUT-1801 INBOX and
`/home/acdev/strikes/synth/context/report-structure-15oct.md`. The later 27-item
list supersedes the text export's 23. Existing eight-dimension C5 remains the
source; no prompt/model activation, scoring, new evaluation, regeneration,
financial writer, schema or access change is part of this projection.

## Coverage before this change

No stored `ReportDraft` has 27 independent pointer assessments or approved
numeric scores. Eight broader dimensions supply related analysis only. A
missing individual assessment cannot mean the behaviour was not observed or
not applicable. Each pointer therefore has `status: insufficient_evidence`,
`score: null`, `score_status: not_scored`, `rating: null`. Existing observations
are useful even with no individual assessment; they are labelled separately.
`evaluated`, `not_observed`, `not_applicable` remain reserved statuses for a
future explicitly supported contract, not statuses inferred by this adapter.

| # | Pointer | Existing source / coverage |
|---|---|---|
| 1 | Call Opening & First Impression | Related human_connection_trust only; a missed conversational opening is not the call introduction |
| 2 | Purpose & Agenda Setting | `report_content.purpose` when present; no separate agenda assessment |
| 3 | Tone and Energy | Related communication_tonality only; no separate energy assessment |
| 4 | Active Listening | `pillars.deeper.listening` when present |
| 5 | Asking Open-Ended Questions | Related discovery_deep_understanding; punctuation counts cannot identify question type |
| 6 | Asking Enough Questions | Measured punctuation counts; no sufficiency judgment |
| 7 | Understanding the Prospect's Role | Related qualification only |
| 8 | Identifying Needs and Challenges | Related discovery_deep_understanding only |
| 9 | Exploring Current Solution | Related discovery_deep_understanding only |
| 10 | Quantifying Business Impact | Related problem_impact_desire only |
| 11 | Understanding Decision Process | Related qualification only |
| 12 | Identifying Stakeholders | Related qualification only |
| 13 | Handling Objections | Existing objection_analysis findings; related certainty_objection_intelligence |
| 14 | Positioning Solution Value | `pillars.deeper.value_connection` when present; related solution_relevance_presentation |
| 15 | Discussing Pricing | `pillars.deeper.price` when present; measured price mentions are not deal values |
| 16 | Handling Competition | Related certainty_objection_intelligence; no separate assessment |
| 17 | Checking for Concerns | Related certainty_objection_intelligence; no separate assessment |
| 18 | Next Steps | `pillars.next_step` / `report_content.next_step` |
| 19 | Call Control | Related communication_tonality; no separate assessment |
| 20 | Question to Talk Ratio | Existing deterministic questions/talk timing; no ratio-based judgment |
| 21 | Handling Silence | Existing timing only; silence quality not assessed |
| 22 | Professionalism | Related communication_tonality; no separate assessment |
| 23 | Closing Attitude | Existing closing_analysis findings; related closing_decision_management |
| 24 | Building Rapport | Related human_connection_trust only |
| 25 | Presenting the Solution | Related solution_relevance_presentation; kept distinct from #14 |
| 26 | Creating Value | Related problem_impact_desire / solution_relevance_presentation only |
| 27 | Overall Communication | `pillars.deeper.communication_note` when present |

Exact owner-title matches in existing findings may add an observation, never a
score or individual assessment. No keyword classification of arbitrary titles.
For older reports, absent optional fields remain null/empty; existing content
and evidence are preserved. `why_it_matters` and `how_to_improve` are copied
only from an existing linked explanation/replacement behaviour, never authored
by this read adapter. No approved per-pointer training-video link exists in the
current report schema: `training_video: null` rather than an invented URL.

## API contract

Existing `GET /v1/conversation/acquisition/submissions/{id}/report` keeps its
source-bound report envelope, private headers, authorization and legacy fields.
For claimed accounts only, `report.content.structure` is additive:

```json
{
  "version": "report-structure/1",
  "overview": {
    "summary": "Existing saved summary",
    "evidence": [],
    "score": null,
    "score_status": "not_scored",
    "biggest_strength": null,
    "biggest_improvement": null,
    "call_statistics": {
      "status": "unavailable",
      "duration_ms": null,
      "talk_share_percent": {"rep": null, "prospect": null},
      "questions_asked": {"rep": null, "prospect": null},
      "longest_turn": null,
      "longest_rep_turn": null,
      "speakers": [],
      "rules": "call-metrics/3",
      "question_count_method": "transcript_question_marks",
      "role_status": "unavailable"
    }
  },
  "pointers": [{
    "id": "call_opening_first_impression",
    "number": 1,
    "label": "Call Opening & First Impression",
    "status": "insufficient_evidence",
    "status_reason": "No separate assessment for this pointer is saved.",
    "score": null,
    "score_status": "not_scored",
    "rating": null,
    "coverage": "unavailable",
    "what_happened": null,
    "why_it_matters": null,
    "evidence": [],
    "how_to_improve": null,
    "training_video": null,
    "observations": [],
    "related_dimensions": [],
    "related_findings": []
  }],
  "final_call_outcome": {
    "status": "unavailable",
    "outcome": null,
    "basis": null,
    "deal_value": null,
    "revision": 0,
    "follow_up_on": null,
    "lost_reason": null
  }
}
```

`pointers` always contains all 27 entries in owner order. Evidence retains
`segment_id`, literal `quote`, `start_ms`, `end_ms` from the validated report.
Observations also retain a `source` field naming the existing saved field.
`related_dimensions` preserves the broader dimension id, label, status,
observation and evidence; it does not promote that status to the pointer.
`related_findings` preserves broader existing objection/closing analysis without
reclassifying closing execution as closing attitude.
`coverage` is `existing_observation`, `related_analysis`, or `unavailable`.
A highlight is `{text, evidence, source}`. A training video, when a future
approved source exists, must have its own approved title/URL; this adapter emits
null. Scores remain null for every current format, including provider extras.

Call statistics use the existing `call-metrics/3` implementation on the same
source/revision's authorized, privacy-projected transcript. Question counts mean
question-mark groups, not semantic question counts. Role shares are percentages
of all attributed speaking time (overlapping speech counted per speaker), not
elapsed call duration. Per-speaker entries preserve id, existing role/source,
talk time, talk share, questions and longest turn. Role totals require a complete
role map with both rep and prospect; ambiguity leaves them null while preserving
speaker-keyed measurements. The longest turn has speaker_id/start_ms/end_ms/
duration_ms; seek bounds are null when the existing detector’s three-turn
publication cap excludes the longest rep turn, while its complete per-speaker
duration is preserved. Missing transcript or a source/revision mismatch leaves statistics
unavailable. Redacted transcript text makes question counts null, not zero.

Final outcome comes only from the existing human-outcome reader: `won` → `Won`,
`lost` → `Lost`, `follow_up` → `Follow-up Set`, `no_decision` → `Decision Pending`.
No recorded value stays unrecorded; an unavailable read stays unavailable.
Deal value preserves the exact decimal string and currency_code, including zero.
No AI outcome, suggested follow-up, budget, price quote or summary is a fallback
for this person-entered record. The writer and audit trail remain unchanged.

The API composes already authorized readers in sequence on their existing
transaction. Optional missing data cannot remove the report. Guests receive
no extension and no additional reads. No customer data is sent externally.

## Validation

- 108 focused tests PASS in4.27s: new mapping/read-composition/HTTP success and
  authorization checks, existing account/guest projection, provider-structure
  regressions and learner acquisition route guards.
- Ruff lint and formatting PASS across all six touched Python files; strict
  incremental mypy PASS for four runtime sources; API import and scoped
  whitespace checks PASS. Logs retained in1801 `report-structure-*20261016.log`.
- Offline comparison on13 retained reports:351 ordered pointer entries,
  zero quote-copy/source mismatch/projection failures, no score values,
  26 original inputs hash-stable, zero provider calls. These legacy outputs
  supply related analysis for23 pointers each; purpose/pricing/question-talk/
  silence have no separate saved observation. This compares saved outputs;
  it does not claim new inference or current authenticated dev-call acceptance.
- Original provider regression test is unchanged; new mapping tests use
  `test_owner_report_structure.py`. All18 parked terminal source/proof bytes
  match the pre-edit checkpoint. UI edits by the owner's session stay separate.
- Automatic-dev health/source verification follows the Report-only commit.
  Authenticated current-dev Report QA remains unavailable without the existing
  approved session/context; no credential probing or substitute identity used.
