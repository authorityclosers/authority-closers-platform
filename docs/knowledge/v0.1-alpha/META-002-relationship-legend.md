---
id: META-002
type: meta
title: Relationship Legend
status: current
version: v0.1-alpha
updated: 2026-09-01
tags:
  - ac/knowledge/meta
---

# Relationship legend

| Label              | Read as                                                             | Authority consequence                             |
| ------------------ | ------------------------------------------------------------------- | ------------------------------------------------- |
| `controlled-by`    | node behavior is constrained by a controlled source                 | source wins on conflict                           |
| `derives-from`     | repository interpretation was produced from a source                | interpretation is not a replacement authority     |
| `routes-to`        | action or journey opens a browser route                             | route still needs auth and business-state checks  |
| `renders`          | route uses a screen family                                          | pixels do not invent behavior                     |
| `calls`            | screen or implementation invokes an API                             | API remains server-authoritative                  |
| `implements`       | file realizes a contract or decision                                | code evidence is not deployment evidence          |
| `validated-by`     | test gate checks the node                                           | only the named gate and result are covered        |
| `evidenced-by`     | named artifact observed behavior                                    | evidence is scoped to its SHA/date/environment    |
| `constrained-by`   | guardrail limits activation or interpretation                       | a P0 blocks its capability, not the whole project |
| `supersedes`       | newer decision replaces an older assumption without erasing history | both records remain traceable                     |
| `known-limitation` | missing proof or unresolved capability is explicit                  | no optimistic inference is allowed                |
| `hands-off-to`     | workstream leaves a bounded next action                             | does not assert an active or assigned agent       |

Relationship labels appear before wiki links in node bodies. Markdown links point to real repository files; wiki links connect graph nodes. Return to [[README|Start here]].
