# Research/source manifest

`source-manifest.csv` is the machine-readable ledger for this package. Every
controlled item was fetched read-only by its exact Drive ID or URL on
2026-09-03. Filenames were not used as a retrieval key.

The first seven rows are the mandatory order from the Master Index. The
remaining rows are the product, UX, UI, technical and assurance sources
needed for an Admin/Instructor workflow package. AC-UXA-01 is used for service
recovery and accessibility; AC-SVAL-01 is used only to preserve the human-
confirmed scoring boundary. Neither assurance document authorizes a new role,
route or score behavior.

## Evidence-to-package use

| Evidence area | Controlled sources | Package interpretation |
| --- | --- | --- |
| Host and route boundary | IA, Admin, ADR-006 | Admin host is separate; Instructor Studio remains a label, not a new host |
| Program/content model | BRD, AC-IMP-04, PRD, SRS, Data/Tenancy | Program → Module → Activity with versioned content and immutable published history |
| Operator roles | Admin, Security, BRD | Canonical roles are listed without merging or expanding permissions |
| Recovery and accessibility | AC-IMP-03, UX States, AC-UXA-01, Mobile/PWA | Explicit states, recovery ownership, focus/target-size/reflow requirements |
| Assessment | PRD, SRS, AC-SVAL-01, ADR-017/020 | Authoring/review is bounded; official score authority remains human-confirmed |
| Media/provider boundary | SRS, API/MCP, AC-IMP-03, DevOps/SRE | Lifecycle and adapter are described; vendor behavior is blocked |
| Audit and canonical facts | Data/Tenancy, Telemetry, Admin, Security | Audit is restricted/tamper-resistant; analytics cannot grant access or rewrite state |

## Evidence labels

- `controlled`: directly stated or structurally registered by a fetched source.
- `design inference`: a bounded layout, ordering or copy recommendation that
  does not change business semantics.
- `blocked`: a missing contract or capability gate. The package must not turn
  it into a default.
- `reference-ready`: coherent enough for human review and contract work;
  implementation and visual approval are still absent.
