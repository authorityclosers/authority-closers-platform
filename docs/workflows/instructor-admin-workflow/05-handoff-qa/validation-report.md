# Validation report


## Scope

Package: `AC-WF-INSTRUCTOR-ADMIN-V0.1` (`0.1-alpha`)<br>
Branch: `codex/instructor-admin-workflow`<br>
Base: `2a499cfad0e1af5913c905852ece1ee7345de35b`<br>
Validation script: `scripts/validate-package.ps1`

## Expected checks

The deterministic validator checks:

1. required artifact paths;
2. JSON parseability;
3. state CSV header, row shape and stable flow/screen/state references;
4. screen-inventory and state-matrix route/screen consistency;
5. exact source-ID/URL correspondence in the source CSV;
6. local Markdown link targets;
7. PlantUML and manifest references;
8. docs-only package scope.

## Latest run

**PASS — 2026-09-03.** Executed from the package root:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\validate-package.ps1
```

```text
VALIDATION_PASSED
Artifacts: 24; sources: 24; screens: 12; matrix rows: 29
JSON, CSV, Markdown links, PlantUML IDs and docs-only scope checks passed.
```

Any future failure is a release blocker and must be fixed in the docs package,
not bypassed.

## Evidence gaps

- No application implementation or current route/authz/tenant test evidence
  exists in this package.
- No approved Instructor role/permission union, assessment schema/approval
  contract, media provider/limits/retention contract or Admin subroute
  addendum exists.
- No brand tokens, approved Admin fixtures or visual/device evidence exists;
  only text wireframes are supplied.
- Gemini/Antigravity ideation could not run because the installed Gemini
  client returned `IneligibleTierError`; no model output is relied upon.
