---
id: SRC-050
type: source
title: Trust, Verification, and Operations Sources
status: controlled
version: v0.1-alpha
updated: 2026-09-01
controls:
  - "[[GATE-003-exact-release-staging]]"
  - "[[GATE-004-production-activation]]"
tags:
  - ac/source/controlled
  - ac/source/operations
---

# Trust, verification, and operations sources

| Source                                                                                                                                        | Exact controlled ID                            | Applied boundary                                                            |
| --------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------- | --------------------------------------------------------------------------- |
| [Security, Privacy, IAM, Compliance & Audit](https://docs.google.com/document/d/1rFTiq7BI4dpLLMIDacC8qMhpAbAmOct8W_I65Ydqbmw/edit)            | `1rFTiq7BI4dpLLMIDacC8qMhpAbAmOct8W_I65Ydqbmw` | tenant isolation, consent, privacy lifecycle, append-oriented audit         |
| [QA, Verification & Release Gates](https://docs.google.com/document/d/1DUx9JIHNC1KCR62Qso6KTFPoBxmfhU6GSuNqSl87hBg/edit)                      | `1DUx9JIHNC1KCR62Qso6KTFPoBxmfhU6GSuNqSl87hBg` | business, authz, state, integrity, recovery, accessibility and device proof |
| [DevOps, Environments, SRE, Backup & Observability](https://docs.google.com/document/d/1r1P2XdYSY8XhcgLR6icYqhlN1vEbqKagj8Rb16JpcJs/edit)     | `1r1P2XdYSY8XhcgLR6icYqhlN1vEbqKagj8Rb16JpcJs` | immutable releases, staging smoke, restore and side-effect hold             |
| [Admin, ERPNext & Business Operations](https://docs.google.com/document/d/12-VjN02jx8M7S8wJrZLcl4OwLcXIFGXKu74wxdJrWuY/edit)                  | `12-VjN02jx8M7S8wJrZLcl4OwLcXIFGXKu74wxdJrWuY` | narrow product admin, reasoned append-safe correction, ERP boundary         |
| [Telemetry, Analytics, Experimentation & AI Evaluation](https://docs.google.com/document/d/1ggdrD_ldZL3ItJsAMONq_ygQFjbR6dOURpeHGXd4M4I/edit) | `1ggdrD_ldZL3ItJsAMONq_ygQFjbR6dOURpeHGXd4M4I` | canonical facts vs lossy analytics and operational telemetry                |

- controls: [[DEC-001-public-learner-tenancy-consent]], [[DEC-003-canonical-progress-evidence]], [[GATE-003-exact-release-staging]], [[GATE-004-production-activation]].
- evidence map: [[EVD-001-staging-27fafae]], [[EVD-002-auth-81635d1]], [[EVD-003-current-candidate-design-qa]].
