---
id: SRC-030
type: source
title: State, Interface, and UX Assurance Sources
status: controlled
version: v0.1-alpha
updated: 2026-09-01
controls:
  - "[[SF-SYS-001-universal-states]]"
  - "[[VAR-RESP-001-responsive]]"
tags:
  - ac/source/controlled
  - ac/source/ux
---

# State, interface, and UX assurance sources

| Source                                                                                                                             | Exact controlled ID                            | Applied boundary                                                               |
| ---------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------- | ------------------------------------------------------------------------------ |
| [UX State Specification](https://docs.google.com/document/d/10HzU7kLk78WBHd_Y23jYaP0rIaScq7gW27e5D7D-08E/edit)                     | `10HzU7kLk78WBHd_Y23jYaP0rIaScq7gW27e5D7D-08E` | universal presentation states and route-specific recovery                      |
| [UI Design System & Component Specification](https://docs.google.com/document/d/1y7yCqro9ABW8Yn61ZVmnLV8eGlelcq3BisCDTx40SsI/edit) | `1y7yCqro9ABW8Yn61ZVmnLV8eGlelcq3BisCDTx40SsI` | semantic tokens, explicit component state, responsive/accessibility rules      |
| [AC-UXA-01 editable assurance source](https://drive.google.com/file/d/1ZRyNPkkfc8DsBAlpKE9ksb6Oi-nB9BX-/view)                      | `1ZRyNPkkfc8DsBAlpKE9ksb6Oi-nB9BX-`            | three-layer state model, service recovery, accessibility and cohort non-claims |

The three layers are: presentation state, canonical business state, and recovery/operator state. A generic error or spinner cannot substitute for a named business state.

- controls: [[SF-SYS-001-universal-states]], [[ACT-02-reflection]], [[VAR-RESP-001-responsive]].
- validated by: [[GATE-002-G1-free-course]] and [[GATE-003-exact-release-staging]].
- local state matrix: [state-transition-matrix.csv](../../workflows/v0.1-alpha-experience/02-ux-state-spec/state-transition-matrix.csv).
