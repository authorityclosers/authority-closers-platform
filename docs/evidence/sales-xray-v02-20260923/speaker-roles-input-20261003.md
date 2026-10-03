# AUT-311 S4a: dormant speaker-role context

Source: main `c387b2d1`, contract rev 3 / ADR 0042. S4 is split at the
plan/dispatch boundary because open PR #251 owns `reporting_pipeline.py`.
This slice adds a pure names-free snapshot validator and optional C5 context,
plus the five closed alignment origins. The helper lives in `speaker_roles.py`
so the next slice can reuse it without putting database logic into reports.

`SPEAKER_ROLE_PROMPT_REVISIONS` remains empty. No production revision consumes
roles. The patched declaring-revision test checks detached context, matching
C2 revision, role provenance, unchanged source turns and context validation.
Known speakers, unique labels, at most one account holder, seller-only holder,
strict booleans, the 32-speaker bound and forbidden extra/name fields are checked.
Incomplete confirmed/channel maps are refused; uncertain maps may omit unresolved
roles. Invalid input raises only `speaker_roles_snapshot_invalid`; fallback
resolution belongs to the later plan assembly. No scoring or enforcement is added.

Alignment echoes only the five approved origins; `voice_match`, verified identity
and malformed origins still fail. Segment identity stays unverified and channels
stay unmapped. C2 inputs are unchanged. The S3 actor assertion is now an explicit
denial, with a missing-actor regression case.

## Verification

- 198 distinct focused tests passed: 88 context/alignment/prompt cases; 96 v5/v6,
  report-store and speaker-map regressions; 14 HTTP/service cases. The service
  suite was repeated after adding its missing-actor case.
- `uv run ruff format --check packages/python tests`,
  `uv run ruff check packages/python tests`, `uv run mypy packages/python`: pass.
- All fixtures are fictional. No provider call, usage, database or runtime change.

### CI source-pin correction

The first CI run at `0ad29a88` failed only
`test_report_validator_revision_pins_reviewed_source_and_numeric_key_semantics`:
the optional context changed `reports.py`, while the revision-7 source pin still
described main. The failure was reproduced locally. Context validation now admits
the optional names-free snapshot, so the source-owned validator identity advances
to `ac.sales-xray.report-validator/8` and the test pins the resulting module hash
`8ea811449988044c4745965b82b1349f2f67881eebb4ebae70f74f890b93c896`.
Retained recovery uses this new identity; existing audit/history rows stay intact.

After correction, 227 tests passed across reports, speaker-role input, alignment,
source context, prompt revisions, retained C5 recovery and failure details. Ruff
format/check and mypy pass. The earlier 198-case result remains the original slice
proof; these overlapping follow-up cases are not added to it as distinct tests.

The canonical JSON prompt bodies were compared directly with the reports module
from pinned main (using the fictional `source_and_facts` fixture, Gemini 3.8 Flash,
the unchanged profile and each revision's pack). All six were byte-identical:

| Revision | SHA-256                                                            |
| -------- | ------------------------------------------------------------------ |
| v1       | `6b56e9d36b75faa090c105360bb4b8a729a79b5a5e4a0722d6733abbe07472f8` |
| v2       | `b6554dd1b542971e09042da1bf0c324adbec046bba66b438594b66184856260d` |
| v3       | `5756ae9491663a8fec406da1bd3e457082b85ff5ace31c7a4f3c7bebe8695355` |
| v4       | `3b71e92d051592767f0f26f92dfabcad1db8b444994591e59ca2db6490763abb` |
| v5       | `fd30c8f3849f668ecea1f6fcdff0e8b51476734fb8b0ecd46e2431c76d374edd` |
| v6       | `9e4bcb6f57323e8eeb28c8714eb1992f6acd09d7168581ce6fdbe18e7833530e` |

## Dev and continuation

At https://salesxray-dev.authorityclosers.com, site and API readiness return 200.
Dev OpenAPI still omits S3's speaker-map route; authenticated live S3 behavior is
unverified. S4a has no screen behavior: reproduce with the new
`test_speaker_roles_report_input.py` and existing alignment/source-context suites.
No real call was opened. StageRequest/prepare/dispatch plumbing, once-per-plan
freezing with the actual customer owner, fallback resolution and `report_basis`
remain S4b; S5 model-name parsing remains separate. AUT-311 is not complete.
