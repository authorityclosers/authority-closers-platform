# QA and release checklist


Status: **reference-ready package; implementation/release approval blocked**.
The checklist is evidence-oriented and does not claim that the application
exists.

## Package integrity

- [ ] Required package artifacts exist: README, brief, source ledger,
  journeys, screen inventory, state taxonomy, behavior spec, route contract,
  state CSV, visual gate/wireframes, AI context/prompt pack, editable diagram,
  component contract, asset/diagram manifests, decision log and validation
  report.
- [ ] JSON parses; CSV parses with the required 17-column schema; no duplicate
  stable IDs, route records or state names.
- [ ] Every local Markdown link resolves; every source URL contains the exact
  Drive ID listed in the manifest.
- [ ] PlantUML uses screen/flow IDs that are present in package artifacts.
- [ ] Diff is docs-only plus deterministic validation; no app code, DB,
  secrets, provider keys, deployment or production state.

## Workflow/state behavior

- [ ] Authoring covers Program → Module → Activity, draft preservation,
  dependency validation, version conflict and immutable publication.
- [ ] Enrollment/progress oversight uses canonical enrollment/progress/
  evidence and safe recovery; analytics cannot become authority.
- [ ] Assessment stays `blocked` until schema/attempt/approval contracts and
  AC-SVAL gates exist; official authority remains human-confirmed.
- [ ] Course media uses provider-neutral lifecycle and never activates
  real-call recording/transcription/external AI.
- [ ] Audit/recovery preserves original history, records reason/reference and
  escalates by layer; no raw DB repair path.
- [ ] Every mutation has server authz, tenant/context check, idempotency and a
  durable result; retries cannot duplicate side effects.

## Accessibility/recovery evidence to require before production

- [ ] Keyboard-only route, tree/editor, table/card, dialog, stepper and retry
  flows with visible focus and focus restoration.
- [ ] Screen-reader labels and live announcements for loading, async,
  validation, stale/offline, denied, conflict, reconciliation and success.
- [ ] Non-color status, contrast, zoom/reflow, 44pt/48dp target checks and
  reduced-motion checks on compact and wide Admin layouts.
- [ ] Injected failures and recovery drills cover lost draft, session expiry,
  duplicate action, provider timeout, stale read model, restore hold,
  reconciliation and replay idempotency.
- [ ] Support/view-as masking, duration and ownership tests exist before any
  view-as route is enabled.

## Controlled QA mappings

| Concern | Existing controlled QA cases to execute when code exists |
| --- | --- |
| Published immutability/dependency/version | TC-019, TC-020, TC-021, TC-022 |
| Rubric/override/queue boundary | TC-036, TC-037, TC-042 |
| Upload consent/malicious/provider behavior | TC-040, TC-041, TC-063, TC-068 |
| Sensitive correction/view-as | TC-057, TC-058 |
| Replay/restore/reconciliation | TC-060, TC-066, TC-067 |
| Offline/stale/no false sync | TC-065 |

## Release gates

`reference-ready` can hand off to contract/design review. `production-approved`
requires source updates, role/route/schema/provider decisions, implemented
server-side authz/tenancy, automated and manual QA evidence, AC-UXA recovery
and accessibility evidence, and applicable AC-SVAL/AC-GOV-AUD gates. A P0
blocks only its capability; it does not authorize building a different future
product.
