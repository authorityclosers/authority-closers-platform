# Future design/critique prompt pack


These prompts are guardrails for a later design tool or reviewer. They are not
instructions to implement a product now. Attach the package JSON, route
contract, behavioral spec and state CSV when using one.

## P-01 — Workflow critique

> Critique `AC-WF-INSTRUCTOR-ADMIN-V0.1` as a docs-only Admin workflow. Check
> stable IDs, actor boundaries, state coverage, recovery ownership,
> version/audit semantics and desktop/compact reflow. Cite the exact source
> key or `BLK-*` for every finding. Do not invent permissions, billing,
> learner counts, score behavior, provider behavior, B2B UI or publication
> policy. Return findings as `finding_id`, `severity`, `screen_id`, `evidence`,
> `risk`, `blocked_or_actionable`.

## P-02 — Responsive interaction pass

> Produce a non-branded layout critique for the registered routes only. Use
> UI System semantic tokens and breakpoints. Preserve the same actions and
> state names across wide and compact compositions; replace dense tables with
> stacked records where needed. Do not choose hex colors/fonts, add routes or
> create a native app. Flag every missing role/route/assessment/media rule as
> `blocked`.

## P-03 — Accessibility/recovery pass

> Inspect the state matrix for keyboard order, focus after route/error/async
> changes, labels, target sizes, zoom/reflow, reduced motion, non-color status,
> stale/offline messaging and lost-draft risk. Map gaps to AC-UXA-01 and QA
> case IDs. Never use a toast as the only outcome; never recommend a raw DB
> repair path.

## P-04 — Assessment gate review

> Review only the assessment authoring/review boundary. Confirm that the
> package does not invent question schema, attempt limits, rubric fields,
> approval ownership, score classes or official AI behavior. Keep the route in
> `blocked`/`assessment_authoring_blocked` until the controlled assessment and
> AC-SVAL gates are approved. Preserve immutable evidence and human-confirmed
> official authority.

## P-05 — Media/provider gate review

> Review course-media dependency and the provider-neutral lifecycle
> `EXPECTED → UPLOADING → PROCESSING → READY|FAILED → RETIRED`. Verify retry,
> conflict, stale and provider-failure states without selecting a vendor or
> claiming codec, size, SLA, retention or resumability. Keep real-call
> recording/transcription/external AI blocked.
