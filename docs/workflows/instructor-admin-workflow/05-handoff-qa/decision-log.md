# Decision and gap log


| ID | Decision/status | Rationale and evidence | Follow-up |
| --- | --- | --- | --- |
| D-001 | Accepted: separate Admin surface | IA, Admin and ADR-006 separate `admin.authorityclosers.com` from learner and ERP surfaces | Preserve host/authz boundary in implementation |
| D-002 | Blocked: Instructor Studio is a label, not a role | Admin role model names Content Manager and Coach / Reviewer separately; no approved union | Resolve `BLK-01` before role-gated UI |
| D-003 | Accepted: bounded docs-only scope | AC-IMP-05 says freeze route/content/state/publication/admin boundary; do not build entire visual/B2B/native set | Keep this branch docs-only |
| D-004 | Accepted: route statuses are explicit | IA registers core routes but leaves progress/audit conditional and does not register media/review/health/view-as paths | Add route addendum before implementation (`BLK-09`) |
| D-005 | Accepted: immutable version lifecycle | SRS/Data/AC-IMP-04 define versioning and `DRAFT → IN_REVIEW → PUBLISHED → RETIRED` | Verify TC-019/020/021/022 |
| D-006 | Blocked: assessment editor/review route | PRD/SRS establish capability but exact schema/attempt/approval contract is incomplete; AC-SVAL gates official authority | Resolve `BLK-07`; retain human-confirmed boundary |
| D-007 | Blocked: provider-specific media behavior | API/SRS define adapter and lifecycle, not vendor/limits/retention/resumability | Resolve `BLK-08`; keep course media provider-neutral |
| D-008 | Accepted: audit/recovery is first-class | Admin, Data/Tenancy, AC-IMP-03 and AC-UXA require reasoned, append-only/superseding history and layered recovery | Verify replay/restore/provider tests |
| D-009 | Accepted: text-only visual reference | UI System has no final Admin brand tokens/assets; no generated image can authorize missing semantics | Resolve `BLK-VIS-01..03` before visual approval |
| D-010 | Recorded: Gemini ideation unavailable | `gemini-3.8-flash-high` attempt returned `IneligibleTierError`; no model output was used and no settings were changed | Human/source review remains the authority |
| D-011 | Accepted: unsupported behavior is blocked | AGENTS.md forbids inference of protected business semantics and full future products | Maintain `BLK-*` register and matrix states |
| D-012 | Accepted: no application code | User requested a workflow/UI architecture package only | Do not add routes, components, API, schema or deploy changes |

## Open questions requiring authority

- Should “Instructor Studio” ever become a separate product label, host or
  canonical role, and if so what exact union/approval boundaries apply?
- Which Admin subroutes and capability flags are canonical for Media,
  Assessment Review, Progress diagnostics, Audit, Health and View-as?
- What assessment schema, rubric/attempt/version/publish contracts and human
  approval separation are allowed?
- Which media provider, file constraints, resumability, retention, captions
  and fallback behavior are approved?
- What exact Admin MFA/step-up, view-as duration/masking and bulk partial
  outcome contracts are required?
- Which non-sensitive fixture data and semantic-to-brand tokens are approved
  for a visual pass?
