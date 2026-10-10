# AUT-1678 implementation evidence

This strike starts at `b6033ad3d3d55f928547e2901785e6e239357bdc`. Its binding definition is the owner’s final Sales Xray structure dated 2026-10-09, §§3, 5, 6, 10 and 12. The module is a provisional read model, not the completed Coaching capability.

## Current behavior

`GET /v1/me/coaching` uses the signed-in account/workspace on the exact Sales Xray host. It accepts no person, workspace or call selector. Coaching is open under AUT-1678 to Personal and human organisation memberships; operations and processing identities are excluded. It does not inspect payment providers, charge credits, call AI, write progress, or renew claims. Responses and errors are private and uncached.

Own retained acquisition history is read through the existing call-library scope and `AcquisitionReports.report`. An organisation administrator’s teammate access never becomes personal learner history. Canonical source, proof, report, ownership, live membership, retention and withholding checks remain authoritative. Withheld references cannot produce playable Coaching evidence.

The adapter connects a report’s first next-call mission to a skill only when its exact evidence uniquely identifies one supported report dimension. Ambiguous prose does not establish that link. Unknown, conflicted, inapplicable or unsupported dimensions do not become failures. Duplicate source uploads count once. Comparable provisional suggestions require a validated durable C5 evaluator receipt: recipe, prompt, model, profile, qualitative pack, language and repair/benchmark boundaries are retained. Legacy/recovered/unlinked reports stay separate.

The learner replay keeps one supported mission across dates and minor new findings. The latest 40 retained calls bound each read, and truncation is disclosed. This is **not durable mission persistence**: loss of retained history can change the replay result. Source-bound call/skill/mission contracts reject crossed source identity and duplicate skills.

The `/coaching` page uses the existing operational page kit and semantic tokens, Devanagari-capable fonts, skeletons, progressive disclosure, and a corner retry card. Evidence loads only on click, seeks to its source timestamp, stops at the excerpt end, and pauses other Coaching players. A workspace/session change remounts the learner view; stale identity responses are rejected. The six narrative pillars expose one practice, a complete structured text lesson, one mission, unknown progress and a provisional path. Agreement/reflection saving is explicitly unavailable.

The lesson source is the approved owner specification’s impact framework and own-call comparison/practice principles. `dipak_report_v1.json` is an unapproved candidate and is not represented as an approved knowledge base. These lessons do not claim Dipak media provenance. Catalogue contracts admit only revision-bound reviewed tags, confirmed Dipak provenance and valid durations; unreviewed proposals are unusable. Actual import, AI tagging and a persisted review queue are not active.

## Proof

Focused tests live in `tests/unit/coaching/`, `tests/database/test_coaching_postgresql.py` and `apps/sales-xray-web/app/coaching/*.test.*`. They cover uncertainty, focus stability, duplicated sources, explicit version boundaries, ambiguous source links, review provenance, private cookie/host/selector access, teammate isolation, withholding/revocation, workspace changes and audio recovery. Database proof uses disposable schemas from `AC_TEST_DATABASE_URL`; all committed calls and quotes are fictional. Ruff, mypy, Prettier, ESLint, TypeScript and focused pytest/Vitest are the local checks. CI supplies full suites and production compilation.

Private strike notes, offline corpus counts and fictional local browser artifacts live outside Git at `/home/acdev/strikes/1678/`. Corpus content must never enter evidence, Git, GitHub or chat. Offline adaptation is not an account-authorized deployed journey, a provider test, or a mastery validation.

## Remaining activation requirements

- Shared migration/model ownership is held by another strike (see the current holder in `NOTES.md`; #414 was followed by #421). Durable learner/skill profiles, focus revisions, diagnosis revisions, missions, practice history, relevant opportunity observations, skill evidence links, reflection/feedback and media review receipts need dedicated canonical tables and superseding audit history. Analytics and unrelated domain tables cannot substitute.
- Current report labels are not relevant-opportunity success verdicts or root-cause diagnoses. No approved threshold rules were supplied for mastery/regression. These stay unknown until reviewed comparable behavior evidence and rules exist; content completion, call count and dates cannot advance mastery.
- #419 holds the sidebar and navigation tests. Add the single Coaching entry after Report and Prospects when ownership clears. The direct page currently inherits the shell’s default selection.
- `/root/ac-drive/index.db` is inaccessible. A read-only export is requested through `NOTES.md`; the four required categories must retain exact Drive IDs/revisions. No fabricated media recommendation, external AI tagging, or provider activation is permitted.
- The named `app/ui/sx-tokens.css` and Windows AC Orchestra skill/authorized Pro browser are absent at the pin. Existing tokens and bounded local implementation are used without editing Strike A’s styling.

CTO/CEO review is required for the new Coaching access rule. This session does not merge, deploy, read secrets, or mutate staging/production. After the approved merge and normal ui-lane sync, open `/coaching` while signed in; inspect the evidence, lesson and mission, then change workspace. Full strike acceptance remains blocked on the requirements above.
