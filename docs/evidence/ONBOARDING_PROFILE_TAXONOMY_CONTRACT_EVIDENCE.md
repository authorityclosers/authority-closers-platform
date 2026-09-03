# Onboarding/profile taxonomy contract evidence

Status: contract-only proposal; no runtime/API/database activation.

## Scope

This evidence record covers the bounded contract for country, separated phone
and WhatsApp endpoints, education level/degree, field/specialization, and
sales-learning interests. It deliberately excludes scoring, personalization,
consent, WhatsApp integration, phone verification, provider data flow, and
protected business semantics.

## Base and isolated worktree

- Base green commit: `2a499cf`.
- Branch: `codex/onboarding-taxonomy`.
- Worktree: `C:\Users\Suyash\.codex\worktrees\onboarding-taxonomy\authority-closers-platform`.
- No push, merge, deploy, or production-state mutation performed.

## Artifacts

| Artifact                                                    | Evidence                                                                                                                       |
| ----------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| `docs/contracts/ONBOARDING_PROFILE_TAXONOMY_CONTRACT.md`    | Human-readable field, normalization, privacy, accessibility, route/API, state, inference, and gate contract.                   |
| `docs/contracts/onboarding-profile-taxonomy-v1.schema.json` | Machine-readable bounded shape; unknown fields rejected.                                                                       |
| `docs/contracts/onboarding-profile-source-manifest.json`    | Exact official source URLs, retrieval date, provenance/licensing decisions, no-vendored-dataset decision, and generation path. |
| `docs/contracts/onboarding-profile-state-matrix.csv`        | Onboarding/profile/settings/routing state acceptance matrix, including recovery and accessibility/privacy boundaries.          |
| `tests/unit/test_onboarding_profile_taxonomy_contract.py`   | Schema/manifest integrity and valid/invalid contract cases.                                                                    |

## Controlled-source evidence

The required source-order documents were fetched by exact Drive IDs on
2026-09-03: Master Index, BRD, AC-IMP-00, AC-IMP-01, AC-IMP-03, AC-IMP-04,
AC-IMP-05. The supporting PRD, IA, UX Research, UX States, UI System, SRS,
Data/Tenancy, API/MCP, Security, Admin, Telemetry, Mobile/PWA, DevOps/SRE,
QA/Release, ADR/Risk, and relevant AC-UXA-01 assurance source were fetched
before drafting. Connector revision IDs are retained in the source-fetch
session; the contract records exact Drive IDs and consequences.

## External evidence and licensing outcome

The source manifest records official ISO, ITU, UNESCO UIS, Government of India
DoT/UGC, and W3C URLs with retrieval date `2026-09-03`. No full country,
numbering, UNESCO, or Indian degree list is vendored: ISO’s free code-use
statement does not make all materials freely reproducible; ITU/UGC/DoT reuse
terms were not established; UNESCO’s related operational manual is
CC BY-NC-ND 3.0 IGO. The repository therefore stores a field contract and a
reviewed fetch/generation path only.

## Verification

Run from the isolated worktree:

```text
uv run pytest tests/unit/test_onboarding_profile_taxonomy_contract.py
```

The test asserts schema structure, field separation, E.164 shape, enum
boundaries, conditional `other` behavior, source URL/retrieval metadata, and
the explicit empty vendored-dataset list. It does not claim that a number is
assigned/reachable, that a degree is recognised, or that any taxonomy is a
scoring/personalization model.

## Gates

- Country `IN` is an inference and must be confirmed before activation.
- Current source revisions, SHA-256 values, and reuse review must be recorded
  by a release-generation job before any generated list is introduced.
- Controlled product/data/API/security/QA promotion is required before code or
  schema migration.
- Privacy review is required for contact-field local drafts, retention, and
  deletion behavior.
- WhatsApp/provider, consent, scoring, AI, call, and B2B semantics remain
  capability-gated and are not opened by these documents.
