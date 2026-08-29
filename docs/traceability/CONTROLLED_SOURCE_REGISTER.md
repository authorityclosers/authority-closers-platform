# Controlled source register

This register pins the documents used for the first implementation baseline. Drive remains the controlled long-form authority; Git records the implementation interpretation and evidence. All listed documents were reported as version 0.5.0 and last updated 2026-08-29 unless noted otherwise.

| Area | Controlled document | Implementation role |
|---|---|---|
| Index | [Authority Closers Master Index](https://docs.google.com/document/d/1gC6BdFZ2LfjrpjM-qPKcX1qWMTUBSAXo3b-AlaOYqus/edit) | Source order, baseline status, ownership |
| Business | [Approved BRD](https://docs.google.com/document/d/1HEp7QN4u3c_636uACznnkruYHhGYHAJWXH7Dlfjybpk/edit) | Founder-approved business rules and authority |
| Product | [PRD](https://docs.google.com/document/d/1vZGxiP5GRA7He0gA7oF6hmTeHqoEZUIJko_QBUtDW_k/edit) | Product behavior and permanent activity model |
| Information architecture | [IA](https://docs.google.com/document/d/1VLJTswU2sqlimfoSIROVvlJ9Z6ue-6Dd45oEcu1ddhs/edit) | Routes, surfaces, hierarchy |
| UX evidence | [UX research](https://docs.google.com/document/d/1M_IlSgZwWfHVk1IU3JBzY-EhT3RIfXO07WII8MbwxPM/edit) | Learner/admin needs and research-backed behavior |
| UX states | [UX states](https://docs.google.com/document/d/10HzU7kLk78WBHd_Y23jYaP0rIaScq7gW27e5D7D-08E/edit) | State register and failure/offline behavior |
| UI system | [UI system](https://docs.google.com/document/d/1y7yCqro9ABW8Yn61ZVmnLV8eGlelcq3BisCDTx40SsI/edit) | Component identifiers and design rules |
| Software requirements | [SRS](https://docs.google.com/document/d/1qE_ASXOBN-AAuIglfs4-5Fi_HN3x-jDItBYdb95Ou2g/edit) | Functional/non-functional requirements and state machines |
| Data and tenancy | [Data / tenancy model](https://docs.google.com/document/d/1SUxNYTu30NXwBEbk7os1OBVn4H5qBky-LnzLuOvwaYw/edit) | Entities, tenant invariants, persistence semantics |
| API and agents | [API / MCP contracts](https://docs.google.com/document/d/1kWawS57AGVv7jT5Kp2V0Mk8kK0B6BwPzlG6KiAOtpt0/edit) | API catalogue, events, agent boundary |
| Security | [Security / IAM / privacy](https://docs.google.com/document/d/1rFTiq7BI4dpLLMIDacC8qMhpAbAmOct8W_I65Ydqbmw/edit) | Authorization, privacy, retention, recovery controls |
| Administration | [Admin / ERP](https://docs.google.com/document/d/12-VjN02jx8M7S8wJrZLcl4OwLcXIFGXKu74wxdJrWuY/edit) | Narrow support/admin workflows and ERP boundary |
| Telemetry | [Telemetry](https://docs.google.com/document/d/1ggdrD_ldZL3ItJsAMONq_ygQFjbR6dOURpeHGXd4M4I/edit) | Canonical facts, analytics, OTel, audit separation |
| Client platforms | [Mobile / PWA](https://docs.google.com/document/d/1wxYkUGdHchtSYFpiXxGWQoaT95D4y4LO_qZG7MlEsoI/edit) | PWA/mobile resilience and native migration seam |
| Delivery | [DevOps / SRE](https://docs.google.com/document/d/1r1P2XdYSY8XhcgLR6icYqhlN1vEbqKagj8Rb16JpcJs/edit) | Build, deploy, observability, backup and restore gates |
| Verification | [QA / release](https://docs.google.com/document/d/1DUx9JIHNC1KCR62Qso6KTFPoBxmfhU6GSuNqSl87hBg/edit) | Test evidence and release acceptance |
| Decisions and risk | [ADR / risk](https://docs.google.com/document/d/1cNE-8DB0iX28U5IR_StkO-JGE2TPG-pbKn6LQ-bZSaY/edit) | Accepted architectural decisions and active risks |

## Source corrections and drift

- The supplied UX-states identifier ending in `IaSq` returned 404. The live same-parent document ends in `IaSc` and is the link registered above.
- Paid-commerce passages describe later capability. The 2026-08-29 implementation transition and approved BRD make explicit free enrollment the first-slice authority.
- Several documents still label founder questions unresolved even though the ADR register and approved BRD mark them closed. G0 must reconcile that status language before G1 can pass.
- No source formally defines G1. ADR-025 proposes the definition used by this repository and requires controlled-document promotion.
