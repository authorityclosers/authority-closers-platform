# Human call outcome preparation — AUT-1677

Owner inbox: 11 October 2026, about 04:50 IST. Implementation prepared after main 43d6eaf. These controls and value contracts do not mount an API, write data or claim outcome persistence.

The bounded human command supports Won, Lost with a required reason, Follow-up with a required calendar date and No decision. Unrecorded and unavailable remain distinct. An optional deal value retains an exact nonnegative decimal string and an explicit three-letter currency code; it does not infer a currency, round or convert amounts, use AI qualification or couple to payments.

The controlled editor requires caller-provided edit authority and a save callback. Its scope key discards drafts when person, tenant, session or call changes. Won and No decision issue one command; Lost and Follow-up require the extra human input. Pending saves reject duplicate commands. Failed saves show a small retry card, and the displayed recorded value changes only through the parent's server read-back.

Verification:

- 47 focused Python value-contract cases, strict module mypy and ruff pass.
- 39 focused frontend value/control cases, app typecheck, changed-file ESLint and Prettier pass.
- Fictional browser proof at 390 and 1440 px in light and dark exercises required reason, human date, explicit amount/currency, failed save and retry. The recorded value remains Unrecorded; phone controls are at least 44 px, with no horizontal overflow, page errors or external requests. Screenshots were inspected and the temporary preview stopped.

Private screenshots and the count-only receipt are in `/home/acdev/strikes/1677/shots/call-outcome-current`. The dev-only route is `/review-fixture/report/outcomes`; its callback always rejects and never pretends to save a fact.

Remaining: additive append-only outcome and prospect-stage storage, atomic audited commands and mounted read/write APIs, rep/assigned-manager policy, real Report/Prospect integration and Admin/people-feed consumers. The shared migration slot is held by #436. Billing owner/admin roles do not imply manager authority. Proposed API and transaction fences are recorded privately in `/home/acdev/strikes/1677/outcome-api-handoff.md`; no API-ready announcement has been made.
