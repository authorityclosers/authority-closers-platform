# Hosted stage source supplement evidence

This change adds a bounded, immutable staging/test supplement for one hosted C5 plan. A supplement binds the canonical human owner, tenant, source, current base approval and processing configuration, language, logical plan, and prepared primary input. Its request and cost allowances are append-only and do not reset existing approval history or expand the base policy. It authorizes at most one primary C5 request and one linked repair; production bundles reject supplements. Completed C2 cache reuse above the base request count requires the existing task, quote, acceptance, permission lineage, checkpoint, and validated provider receipt to match. A fresh C2 request remains subject to the original cap.

The PostgreSQL proof uses synthetic source and provider responses with the normal paid-accounting path. It starts with retained C2/C4 results and historical C5 reservations, quotes and accepts an exact-language plan, races two primary requests with distinct idempotency keys, and runs the scheduler through one primary and one repair. Assertions verify one task and one supplemental reservation for the concurrent primary, no duplicate C2/C4 tasks, preserved historical reservations, denial after the two supplemental slots are consumed, and successful plan completion. It also checks denial for a mismatched language. The fixture is one C4 chunk; it does not claim a live-provider delivery or production activation.

Verification:

- `tests/database/test_stage_supplement_postgresql.py::test_paid_exact_source_supplement_completes_primary_and_one_repair`: 1 passed against disposable local PostgreSQL; synthetic broker only.
- Focused existing PostgreSQL regression selection: 5 passed, covering ordinary C2/C4/C5 reuse, same-source request caps, concurrent carried-budget caps, and normal C5 repair processing.
- Focused conversation-intelligence unit tests: 53 passed.
- Ruff check and format check passed for the changed package and test files.
- Mypy passed for the four changed conversation-intelligence package modules.

No provider calls, live activation, production database changes, or deployment were performed for this evidence.
