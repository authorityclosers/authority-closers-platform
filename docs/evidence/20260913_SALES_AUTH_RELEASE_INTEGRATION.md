# Sales authentication integration — 13 September 2026

Sources38e5e8d7e62509a74d9e775d739b13a000cea728 and15a8ee8e05c32ff3accb7ee21976dd8212d1384a are integrated as a466b14 and3f6dd80.

The worker conflict was resolved by keeping the class method delegated to the shared canonical password-message resolver. That resolver explicitly accepts V1, course-context V2, and Sales-context V3 jobs; only V3 adds the allowlisted /sales-xray continuation. The initial-held verification bootstrap remains exact V1. Media and conversation worker composition are preserved.

Validation on the combined tree:175 worker/outbox/bootstrap and Sales-auth HTTP tests passed. Changed worker Ruff lint/format and mypy passed. This is integration evidence; hosted Sales browser acceptance and the immutable combined release are still pending.

The canonical deployment smoke now probes /sales-xray on the existing learner host with its environment route marker. The existing controller regression suite passed15tests. This establishes page routing only; authenticated workspace and actual provider processing require separate browser/runtime acceptance.

Settings Google-link source4d49d9a integrated as07be8b2 without conflicts. Combined HTTP authentication and status90tests passed, full mypy233sourcefiles passed, and full web Prettier check passed. Actual local browser acceptance is owned by the UI source lane; hosted acceptance will follow the immutable release.

The pinned Ruff0.16.5 whole-tree release check found17 formatting-only mismatches across accepted Sales/media sources. Root applied the pinned formatter; whole-tree Ruff lint and formatting now pass. Full mypy after hosted-authority integration passed237 source files. These are release integration fixes, not provider or publication acceptance.

Media activation source5c8b392 integrated as2358e3c; actual scanner upgrade, clean/EICAR, hard8GiB allocation and both environment media-root readiness passed. Source714e7d5 integrated as4593664 adds the actual live0029-to0031 recovery rehearsal rather than requiring an intermediate application release. The combined test-only Windows isolation fix671475e integrated asb2b8961; it preserves broker credential scrubbing and corrects detached synthetic test environment/model registration. Source profiles and recovery test formatting were normalized with pinned Ruff0.16.5. Current full unit and disposable PostgreSQL recovery acceptance are recorded separately when complete.

## Linux CI typing correction

Accepted source3fd938f6ebee7632d8c4cee153d48e237734137a after CI34731375657 exposed platform-stub errors in WinDLL and the Windows/POSIX file-lock branches. The correction adds narrowly scoped attr-defined/unused-ignore annotations and formatting only. Root inspected the full diff; the UI reviewer confirmed identical executable Python AST against48b4d71. Source full237-file mypy passes both native Windows and explicit Linux platforms; Ruff lint/format passes. Runtime process-tree ownership and filesystem fencing behavior are unchanged. Mandatory exact Linux CI will rerun before deployment.

## Full Linux test corrections

CI34731858764 passed formatting, lint, types, all frontend suites, scanner, privilege and migration/recovery gates; full Python tests exposed38failures and9errors with4711passed. Accepted source db5c5932cc246ca1e595b6179beca0d2c99de5ae corrects three stale test contracts: all14already-mapped conversation tables in the registry expectation; intentional codec/filesystem CI prerequisite naming and packages; and the extracted public-film shell harness's filesystem selector stub. Runtime source is unchanged. Author's focused tests45passed/3environment skips and Ruff passed; root reviewed the full diff. The Linux CI retry must exercise those platform-specific harness cases.
