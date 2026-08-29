# ADR-025: Formalize G1 as Free Course readiness

- Status: Proposed pending controlled-document reconciliation
- Date: 2026-08-30

## Context

The controlled baseline names G0/G1/G2 but formally defines only G0. An undefined gate cannot be used for release approval.

## Decision

Treat G1 as the end-to-end Free Course walking-skeleton readiness gate described in `docs/gates/G1_FREE_COURSE_SLICE.md`. Treat G2 as internal release readiness only after its definition is reconciled in the controlled documents.

## Consequences

- Teams have an auditable target for the first implementation slice.
- No one may claim G1 passed until the controlled source set adopts or supersedes this definition.
- Paid and advanced capabilities remain gated.
