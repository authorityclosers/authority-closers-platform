# Report review fixes

Independent Luna review of the fourteen-part report packet identified two
specific issues. The third improvement hid its business-impact limitations,
and explicit numeric claims could be carried in provider-authored prose.

Every displayed priority now includes its impact limitations and missing
inputs. A three-priority structured-report test verifies the third block.

ReportDraft validation now rejects known explicit score/rating and projected
revenue/profit forms, including Unicode numeric examples, before persistence
or private response projection. Original quoted evidence remains unchanged;
the existing parser still checks each quote against the source. Source prices
and counts in practice instructions remain accepted.

This deterministic check is a backstop, not a guarantee of factual or semantic
accuracy across arbitrary wording or languages. Source validation, draft status,
human review and the numeric-publication hold remain necessary.

Combined candidate validation: 589 Python unit tests passed, 17 explicitly
skipped (16 require the native AudioAtlas build and 1 requires POSIX ownership).
Eight overview UI tests, Sales Xray TypeScript, focused mypy and Ruff passed.
JUnit: `D:/AC-authority-closers-release-audit/combined-sales-unit-20260914.xml`.

The funded-provider packet was also integrated from source commit
`9bbead1be1f54db5221c2b8090a92346192400c8`. Its separate authority/admin database
proof passed 20 tests with native fixtures in
`D:/AC-authority-closers-release-audit/sales-hosted-funded-pg-20260914-9bbead1-native`.
No external provider calls were made by these tests.

The independent review verified all thirteen original overview receipt files
against their Git blob hashes and byte counts. Hosted guest ownership, Gemini
task execution and deployment remain separate incomplete integration work.
