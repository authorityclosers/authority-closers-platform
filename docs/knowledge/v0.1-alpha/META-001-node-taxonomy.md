---
id: META-001
type: meta
title: Node Taxonomy
status: current
version: v0.1-alpha
updated: 2026-09-01
tags:
  - ac/knowledge/meta
---

# Node taxonomy

| Type             | Stable-ID family                                     | Meaning                                                                  |
| ---------------- | ---------------------------------------------------- | ------------------------------------------------------------------------ |
| `moc`            | `MOC-*`                                              | Entry point and graph map                                                |
| `meta`           | `META-*`                                             | Graph conventions and validation                                         |
| `source`         | `SRC-*`                                              | Controlled authority or explicitly labeled repository interpretation     |
| `journey`        | `JRN-*`                                              | Actor goal across stages, routes, states, and recovery                   |
| `visual-board`   | `VJB-*` with `VJS-*` slots                           | Ordered desktop/mobile storyboard; existing embeds or explicit `PENDING` |
| `screen-family`  | source-aligned IDs such as `AUTH-*`, `ACT-*`, `SF-*` | Screen behavior and variants; not visual approval                        |
| `route-family`   | `RT-*`                                               | Browser routes and their auth/data boundaries                            |
| `api-contract`   | `API-*`                                              | Current code-facing HTTP contract                                        |
| `decision`       | `DEC-*`                                              | Accepted or bounded decision with authority and consequences             |
| `implementation` | `IMP-*`                                              | Linked code/configuration files; not runtime proof                       |
| `test-gate`      | `GATE-*`                                             | Required verification and release boundary                               |
| `evidence`       | `EVD-*`                                              | Named observation tied to a date, artifact, and scope                    |
| `limitation`     | `LIM-*`                                              | Known gap or explicit non-claim                                          |
| `workstream`     | `WKS-*`                                              | Worktree-observed handoff grouping without inferred owner or liveness    |

Every Markdown node has YAML `id`, `type`, `title`, `status`, `version`, and `updated`. IDs are unique and stable; filenames may remain readable. See [[META-002-relationship-legend]] and [[VALIDATION]].
