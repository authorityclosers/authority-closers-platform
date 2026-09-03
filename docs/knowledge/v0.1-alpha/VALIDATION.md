---
id: META-003
type: meta
title: Knowledge Graph Validation
status: validated
version: v0.1-alpha
updated: 2026-09-04
tags:
  - ac/knowledge/validation
---

# Knowledge graph validation

Validated on 2026-09-04. These results cover documentation structure and repository paths only; they do not claim application or live-environment proof.

| Check           | Result                                                                                              |
| --------------- | --------------------------------------------------------------------------------------------------- |
| Graph validator | `PASS` — 78 Markdown nodes, 78 unique IDs, 78 unique titles, zero errors                            |
| Relationships   | 649 wikilinks; 210 relative repository file links; all resolved                                     |
| Visual boards   | 12 boards; 82 unique ordered screenshot slots; 49 existing-image embeds; all embed targets resolved |
| Obsidian graph  | 13 unique color groups; traceability display settings active                                        |
| Prettier        | `PASS` for Markdown, validator JavaScript, and Obsidian JSON                                        |
| Whitespace      | `git diff --check` and untracked-target no-index checks: `PASS`                                     |

- validates: [[README|the graph MOC]], [[VJB-MOC-001-visual-journey-boards]], [[META-001-node-taxonomy]], and [[META-002-relationship-legend]].
- executable check: [validate-knowledge-graph.mjs](validate-knowledge-graph.mjs).
- evidence boundary: documentation structure only; see [[LIM-001-known-limitations]].
