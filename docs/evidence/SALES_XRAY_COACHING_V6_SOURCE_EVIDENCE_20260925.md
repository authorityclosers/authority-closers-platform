# Offline coaching-v6 candidate evidence and runtime gate

Date: 2026-09-25  
Pinned implementation comparison: `1ee6a6d893b7a432fa187e3b9b56f6b49cc9dccd`

## Candidate work

The `sx-qualitative-v6-r1` pack, strict report schema, prompt adapters and offline integration tests are available for candidate review. The pack is single-call scoped and has `numeric_evaluation: false`; these properties do not constitute AC-SVAL approval. New settings still default to `coaching-v3`, historical v1-v5 prompt-byte guards remain in place, and `activation_contract.py`'s frozen v5 benchmark is unchanged.

The pack hash is `3caf39aaa32cc64b13c15adcc3614fdab4c8f538ce43257019f70d7612365c0f`. The existing `dipak-14-point-v1` overview version is retained. The eight dimension categories reuse the existing report structure; v6 adds authored seller judgements and coaching recommendations across those categories. Those additions are candidate semantics, not newly approved Dipak policy. This is not a full Brain 3 report-semantic change.

## Source provenance and limits

The repository's [source intake manifest](../plans/sales-xray-v02/source-intake.json) records these exact Drive IDs, captured-text hashes and statuses in the candidate pack:

| Pack source | Controlled capture | Captured text SHA-256 | Status |
|---|---|---|---|
| `brain-2` | [Brain 2.0 — 19 September](https://docs.google.com/document/d/1-dQpveXRW5n6EXlb5cuOk6TEoWs6gwZTjipFsgMfuQc/edit) | `4b68ee14f09cf5d32f9af056e408ffa2e3a6f59133eb8ff2e93ef2d657dbfaa6` | `candidate_not_runtime_policy` |
| `brain-2-1` | [Brain 2.1 — 20 September](https://docs.google.com/document/d/1oWcdr_SqT-xxHbVrWpYw7S16wfEWHpkn6LFeL4CmjCA/edit) | `870dd8a7a06d9eafc4e0e0d4088e82a172a9247f6b61c8fd5d6870c57c0c23f2` | `candidate_not_runtime_policy` |
| `context-sep22` | [Context and role overlays — 22 September](https://docs.google.com/document/d/1KdSYvWv-IJSkew81eVNxNniWqcJpxAm81lz0xfemRaI/edit) | `fa2012ed41ca3b5eb8f2a8ad3dcf854e5f693173400bc9dc39bd4bbc1e951285` | `candidate_not_runtime_policy` |
| `main-training-rulebook` | [Main training rulebook](https://docs.google.com/document/d/1_dz_4YK-c7ombMXfKU1kKlMx2tAUrcdkfnYRXa2T1fA/edit) | `861de3b7b3e26e3286aba8864173a6af7bab135fe4a06a738aa1ed65473bce47` | `candidate_not_runtime_policy` |

These pack mappings are support references, not claims that each authored instruction appears in its cited source. Examples about money or receivables, roleplay and customer commitment, seller assurance, source selection and cross-call inference are authored applications or technical limits. Their mapping to nearby source sections does not approve them as business rules. Source-register statuses remain unchanged.

The controlled [AC-SVAL-01 capture](https://drive.google.com/file/d/11yOvguvLLj4WRi7-gJonWM3nSzkGk0NC/view) is pinned by captured-file SHA-256 `E5D838C877FC14ED7CD29A1EA213E9318B8B16F38F50FDE87E72E1ADBECA1753`. It identifies itself as a scientific design baseline with validation not yet complete. V6 produces AI feedback and therefore requires Gate 2 evidence, including blinded expert review of methodology consistency and grounding, and a challenge-set review for critical harmful or contradictory advice. This work supplies no such evaluation or approval.

## Runtime gate

V6 remains available to offline candidate tests only. Runtime selection fails closed until AC-SVAL-01 Gate 2 evidence and approval are recorded. The quote service, legacy stage selection, direct inference request, saved-plan acceptance and scheduler, and queued provider worker all reject v6 before allowance reservation or provider dispatch. Admin bounds, the selector and CLI do not offer v6; the backend rejects a direct v6 settings save before creating a revision or receipt. If an existing stored settings row names v6, Admin shows it as disabled and requires changing to a supported engine before saving.

The additive migration `20260925_0049_coaching_v6_selection.py` widens only the saved-revision and language-compatibility constraints; it performs no row rewrite. It has not been run against a database. The runtime gate remains authoritative even if the schema permits a v6-shaped stored value. Existing v1-v5 settings are not changed; no staging or live database was migrated.

## Historical compatibility and validation

The historical prompt digests below were captured from pinned `1ee6a6d` and remain asserted by `test_historical_prompt_bytes_match_the_pinned_1ee_revision`:

| Revision | Prompt SHA-256 |
|---|---|
| v1 | `0f36008d427457f2f6257169da44a2fc132befd77090125b94830c364291d65b` |
| v2 | `cc1a72a3c53ab1c0e4a12a8290ff10426f2a5cba74f26f2a1f2fd62d5ff92abc` |
| v3 | `48f227f28c096cd14cc8fb47f1564dcbec959250661261cac58edfc7126c3fde` |
| v4 | `fb54cb104c1fa810c05f996d0686accd8333387135853438fb0d33bff7ce79bb` |
| v5 | `b487064287b8da3ae577e461ae6bdde9b33b94b6a2303a8fd9c48bcdff27acde` |

Offline adapter and schema tests use synthetic inputs only. They do not call providers, generate model reports, or establish report quality. The private coordinator evidence, including the authored research handoff and pending client-contract patch, is retained outside this public repository. The learner client parser remains unchanged in this task, so a complete end-to-end v6 client path is not established.

No default activation, deployment, migration execution, provider call, money/consent/approval change, generated-report quality claim, or commit is included.
