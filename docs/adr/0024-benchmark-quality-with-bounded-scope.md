# ADR-024: Benchmark quality with bounded scope

- Status: Accepted
- Date: 2026-08-30

## Context

The founder's first-course direction intentionally limits breadth. A shallow LMS implementation would create rework and fail the permanent-platform objective, while copying every feature from mature learning products would create uncontrolled scope.

## Decision

Use mature learning products as quality references for clarity, motivation, accessibility, continuity, reliability, measurement, and operational support. Keep the approved first learning outcome as the feature boundary. Implement the smallest permanent primitives deeply and measure their acceptance criteria.

## Consequences

- Quality gates may require more engineering per visible feature.
- Deferred features remain absent even when a benchmark product has them.
- Reusable domain primitives, tests, telemetry, and recovery evidence are part of the feature, not follow-up work.
- "World class" is never an acceptance criterion by itself; evidence is required.
