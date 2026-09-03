# Research and source manifest

Observed: 2026-09-01. Controlled Google documents were read through the Drive
connector using the exact IDs below. Repository sources were read from the
current workspace. This manifest separates authority, evidence, and design
inference.

## Authority order

1. Explicit current user decisions.
2. Ratified legal, product, security, accessibility, and engineering rules.
3. Exact controlled Drive documents in the `AGENTS.md` fetch order.
4. Current repository contracts and traceability records.
5. This package's behavioral spec/state matrix.
6. Approved visual references.
7. External official guidance, used only to refine implementation and QA.

## Required-first controlled sources

| Order | Source                                            | Drive ID                                       | Use in this package                                                  |
| ----- | ------------------------------------------------- | ---------------------------------------------- | -------------------------------------------------------------------- |
| 1     | START HERE — Documentation Control & Master Index | `1gC6BdFZ2LfjrpjM-qPKcX1qWMTUBSAXo3b-AlaOYqus` | authority, source order, baseline                                    |
| 2     | BRD — Business Requirements & Decision Register   | `1HEp7QN4u3c_636uACznnkruYHhGYHAJWXH7Dlfjybpk` | approved business rules and exclusions                               |
| 3     | AC-IMP-00 — Implementation GO Baseline            | `10tKbAIJWONFNTzK2-NHffy4h1wKgoQP7VdJH_K2eR-A` | foundation sequence and no-go boundary                               |
| 4     | AC-IMP-01 — Codex Engineering Handoff             | `1JVnCjDdE79YseM-1PuhvW00xcoicwmhoHtUvEuKKrdU` | exact source fetch and repository rules                              |
| 5     | AC-IMP-03 — Audit Findings Closure                | `1ncsRMiMMiQ39tCn7dV3vpqwUnirY06BgSuVdm_BuIFo` | capability gates and guardrails                                      |
| 6     | AC-IMP-04 — Free Course Foundation Slice          | `1gQnsY1JjphpmOmfyCRZkfI-p0TWZjF1PkY1xF744Gnc` | four shift titles; five-activity loop; first win; state requirements |
| 7     | AC-IMP-05 — G0-G1 Acceptance/Evidence Plan        | `1Vvf1wCA_JjrJQwhkTsgyDM_9179G4M899pWWc3-UdXw` | evidence and exit-gate discipline                                    |

Canonical URLs use `https://docs.google.com/document/d/{Drive ID}/edit`.

## Required product and engineering sources

| Source                                                | Drive ID                                       | Applied evidence                                                                |
| ----------------------------------------------------- | ---------------------------------------------- | ------------------------------------------------------------------------------- |
| PRD — Unified Learning & Sales Practice Platform      | `1vZGxiP5GRA7He0gA7oF6hmTeHqoEZUIJko_QBUtDW_k` | permanent activity model and learner outcomes                                   |
| Information Architecture                              | `1VLJTswU2sqlimfoSIROVvlJ9Z6ue-6Dd45oEcu1ddhs` | `/home`, `/learn`, `/progress`, `/settings`; separate admin host                |
| UX Research, Personas, Journeys & Service Blueprint   | `1M_IlSgZwWfHVk1IU3JBzY-EhT3RIfXO07WII8MbwxPM` | mobile-heavy/time-poor learner; resume; clear next action; First Win hypothesis |
| UX State Specification                                | `10HzU7kLk78WBHd_Y23jYaP0rIaScq7gW27e5D7D-08E` | universal presentation states and recovery requirement                          |
| UI Design System & Component Specification            | `1y7yCqro9ABW8Yn61ZVmnLV8eGlelcq3BisCDTx40SsI` | semantic tokens; responsive modes; no invented brand values                     |
| Software Requirements Specification                   | `1qE_ASXOBN-AAuIglfs4-5Fi_HN3x-jDItBYdb95Ou2g` | executable requirements and state machines                                      |
| Domain, Data, Event & Tenancy Model                   | `1SUxNYTu30NXwBEbk7os1OBVn4H5qBky-LnzLuOvwaYw` | canonical person/tenant/membership/progress boundaries                          |
| API, Webhook & MCP Contract                           | `1kWawS57AGVv7jT5Kp2V0Mk8kK0B6BwPzlG6KiAOtpt0` | API/authz/idempotency boundary                                                  |
| Security, Privacy, IAM, Compliance & Audit            | `1rFTiq7BI4dpLLMIDacC8qMhpAbAmOct8W_I65Ydqbmw` | consent, least privilege, session/privacy rules                                 |
| Admin, ERPNext & Business Operations                  | `12-VjN02jx8M7S8wJrZLcl4OwLcXIFGXKu74wxdJrWuY` | narrow admin/support and correction safety                                      |
| Telemetry, Analytics, Experimentation & AI Evaluation | `1ggdrD_ldZL3ItJsAMONq_ygQFjbR6dOURpeHGXd4M4I` | facts vs analytics; privacy-safe event boundary                                 |
| Mobile, Capacitor, PWA & Store Publication            | `1wxYkUGdHchtSYFpiXxGWQoaT95D4y4LO_qZG7MlEsoI` | web/PWA first; native seam only                                                 |
| DevOps, Environments, SRE, Backup & Observability     | `1r1P2XdYSY8XhcgLR6icYqhlN1vEbqKagj8Rb16JpcJs` | runtime/release evidence boundary                                               |
| QA, Verification, Release Gates                       | `1DUx9JIHNC1KCR62Qso6KTFPoBxmfhU6GSuNqSl87hBg` | test families and exact-release proof                                           |
| ADR, Risk, Assumption, Open Question & Change Log     | `1cNE-8DB0iX28U5IR_StkO-JGE2TPG-pbKn6LQ-bZSaY` | accepted decisions and unresolved risks                                         |

## Assurance source

| Source                  | Drive ID                            | Role                                                                                                                  |
| ----------------------- | ----------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| AC-UXA-01 editable DOCX | `1ZRyNPkkfc8DsBAlpKE9ksb6Oi-nB9BX-` | adversarial learner/admin/recovery/accessibility baseline; requires a three-layer state model and frontstage recovery |
| AC-UXA-01 PDF           | `19eiKLBdm5ziPsqCFZ55f8iHx0DBM43YH` | immutable review form; not separately parsed for this package                                                         |

AC-SVAL-01 was not used because this package creates no assessment/scoring
behavior. AC-GOV-AUD-001 was not activated because the package does not enable
real calls, external AI processing, stores, or provider data flow.

## Repository implementation interpretations

| Local source                                                                          | Role                                                       | Authority caveat                                            |
| ------------------------------------------------------------------------------------- | ---------------------------------------------------------- | ----------------------------------------------------------- |
| `AGENTS.md`                                                                           | guardrails and fetch order                                 | mandatory repository instructions                           |
| `docs/traceability/CONTROLLED_SOURCE_REGISTER.md`                                     | implementation source register                             | Git interpretation; Drive remains long-form authority       |
| `docs/contracts/V0_1_ROUTE_SCREEN_CONTRACTS.md`                                       | current learner route/API contract                         | settings/progress omission recorded as a gap                |
| `docs/traceability/DRIVE_UI_IMPLEMENTATION_MATRIX.md`                                 | exact visual IDs and v0.1 treatment                        | images are not runtime proof                                |
| `docs/traceability/FREE_COURSE_REQUIREMENTS_MATRIX.md`                                | Module 1 requirement trace                                 | no future breadth inference                                 |
| `docs/architecture/V0_1_FOUNDATION_INFORMATION_ARCHITECTURE.md`                       | implementation boundary                                    | repository candidate architecture                           |
| `docs/security/AUTHORIZATION_MATRIX.md`                                               | named permissions                                          | no UI concealment substitutes for server authorization      |
| `docs/contracts/G1_ROUTE_AUTHORIZATION.md`                                            | route/actor/tenant authorization                           | protected resource existence remains private                |
| `docs/contracts/V0_1_TRANSACTIONAL_EMAIL_CONTRACT.md`                                 | verification/reset/welcome mail behavior                   | UI reference is not delivery evidence                       |
| `docs/contracts/PROVISIONAL_SOURCE_GAPS.md`                                           | controlled gaps                                            | gap IDs block affected capability                           |
| `docs/traceability/PLATFORM_SURFACE_STATUS.md`                                        | runtime/evidence ledger                                    | historical/candidate status is not current production proof |
| `docs/evidence/V0_1_ALPHA_HANDOFF.md`                                                 | staging handoff and open boundaries                        | explicitly records self-enrollment and runtime gaps         |
| `docs/adr/0028-separate-public-learner-context-and-consent-backed-free-enrollment.md` | accepted free-enrollment decision                          | supersedes `GAP-ENR-001`; runtime proof remains separate    |
| `docs/contracts/ENVIRONMENT_CONTRACT.md`                                              | public learner tenant and consent configuration            | public learner/operations tenants are distinct; fail closed |
| `packages/python/ac_platform/enrollment/self_attestation.py`                          | exact self-attestation policy implementation               | code evidence, not deployed-runtime evidence                |
| current `apps/learner-web/app` routes and components                                  | `/progress`, `/settings`, theme, and explicit start action | implementation candidates; no live proof                    |
| current onboarding API/UI code                                                        | exact bounded fields/revision behavior                     | read for consistency; this task did not edit code           |

## Approved visual sources

Clarity Grid is selected. Exact screen assets and Drive IDs are in
`../05-handoff-qa/asset-manifest.json`. Study OS and Signal Path are reserves,
not alternative targets. No new raster screen was generated in this package;
the prompt pack requires exact reference attachment before visual work.

## External official guidance

External sources refine accessibility, browser, and theme QA only. They do not
override AC product decisions.

| Source                             | URL                                                                                                                                                                 | Evidence type                       | Design move                                                                                          |
| ---------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------- | ---------------------------------------------------------------------------------------------------- |
| W3C WCAG 2.2                       | `https://www.w3.org/TR/WCAG22/`                                                                                                                                     | normative accessibility standard    | target WCAG 2.2 AA; test focus, authentication, input assistance, reflow, and target criteria        |
| W3C “What's New in WCAG 2.2”       | `https://www.w3.org/WAI/standards-guidelines/wcag/new-in-22/`                                                                                                       | official explanatory guidance       | include Focus Not Obscured and Target Size Minimum in release checks                                 |
| Microsoft Edge PWA overview        | `https://learn.microsoft.com/en-us/microsoft-edge/progressive-web-apps/`                                                                                            | official platform guidance          | verify browser and installed modes as separate runtime contexts                                      |
| Microsoft Edge PWA UX              | `https://learn.microsoft.com/en-us/microsoft-edge/progressive-web-apps/ux`                                                                                          | official platform guidance          | test install/manage/Windows integration without claiming native Windows app                          |
| Apple Configuring Web Applications | `https://developer.apple.com/library/archive/documentation/AppleApplications/Reference/SafariWebContent/ConfiguringWebApplications/ConfiguringWebApplications.html` | official archived platform guidance | test standalone mode and iOS-specific chrome/safe layout; current-device verification still required |
| MDN `prefers-color-scheme`         | `https://developer.mozilla.org/en-US/docs/Web/CSS/Reference/At-rules/@media/prefers-color-scheme`                                                                   | maintained web-platform reference   | implement System theme as an environment preference, not a third palette                             |
| MDN `color-scheme`                 | `https://developer.mozilla.org/en-US/docs/Web/CSS/Reference/Properties/color-scheme`                                                                                | maintained web-platform reference   | align browser controls and reduce mismatched first paint                                             |

## Facts, observations, and inferences

| Type                                 | Statement                                                                                         | Confidence       | Consequence                                             |
| ------------------------------------ | ------------------------------------------------------------------------------------------------- | ---------------- | ------------------------------------------------------- |
| Controlled fact                      | Clarity Grid is selected; broad settings images are extension references.                         | high             | use the direction, not extension breadth                |
| Controlled fact                      | `/settings` and `/progress` exist in controlled IA.                                               | high             | keep both in the bounded learner workflow               |
| Repository fact                      | current app routes/components implement `/settings`, `/progress`, and device-local theme control. | high             | mark candidate/runtime pending; do not claim live proof |
| Accepted decision                    | ADR 0028 fixes the exact consent-backed free-course self-attestation policy.                      | high             | supersede `GAP-ENR-001`; retain exact-runtime gate      |
| Current user decision                | include profile/settings and Light/Dark/System theme mode plus advanced appearance variants globally. | high             | add bounded settings/appearance workflow                |
| Repository fact                      | theme mode and named preset, accent, density, and motion preferences are non-sensitive device-local presentation state. | high             | do not infer account, tenant, authority, or cross-app synchronization |
| Runtime observation                  | historical staging evidence does not prove the current requested complete journey.                | high             | release checklist requires exact-current runtime rerun  |
| Research-supported operating default | WCAG 2.2 AA and 44px AC mobile target intent.                                                     | high/AC-specific | test normative WCAG plus AC design intent               |

## Source gaps

- No account preference API/data model authorizes cross-device, account, tenant,
  or learner/admin theme/appearance synchronization; the current implementation
  is browser-local only. Light/Dark/System remain theme mode, while named
  preset, accent, density, and motion values remain presentation-only.
- `/settings`, `/progress`, and theme are implementation candidates with
  exact-current runtime, accessibility, and browser evidence pending.
- `GAP-ENR-001` is superseded by ADR 0028, the environment contract, and the
  self-attestation implementation; deployment/runtime evidence is still pending.
- Approved media, transcript, caption, and playback evidence remain provider
  and runtime dependent.
- Final brand values and typography assets are not formally registered as
  implementation tokens in the controlled UI document.
- No exact-current Edge installed-PWA or iOS Safari/Home Screen runtime evidence
  is created by this documentation task.
