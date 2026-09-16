# Processing plan repair budget compatibility

The live core release 8937091 emits automatic_c5_repair_cost_paise in every processing-plan response. The web release 763fe8 rejected this known field as plan_unknown_field. Recent uploads therefore obtained quotes but never accepted them, showing a verification error before transcription.

The web parser now validates this additive field as an integer from zero through the already quoted total. It does not add the reservation a second time. Legacy omission means zero. Unknown fields and negative, fractional, null, string, or over-budget values remain rejected.

Validation:
- Full web suite: 266 tests across 27 files passed.
- Production build and TypeScript passed.
- Existing component plan fixtures now include the current server field.
- Read-only production ConversationProcessingPlans.view output for an actual 17-minute guest quote passed the exact new web parser. Total 35560 paise and repair allowance 1000 paise remained unchanged. Private receipt SHA256 bb46ec2ea764d5c44b2b5dd20d7fe1167b620b419c514856ef2f433c975db653. The private fixture was not committed.
- Exact-response parser proof plus focused component tests: 33 passed.

This corrects the plan-admission display boundary. Longer-call provider repair and 60-minute runtime limits require separate verification; this evidence does not claim their success.
