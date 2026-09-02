# Concept evaluation gate

Status: **not started — visual generation pending**

No concepts were generated in this docs-only package, so there is no selected
direction, score, raster asset, or visual approval to report. This explicit
empty gate prevents a visual from silently changing behavior.

When visual exploration starts, produce exactly three independent desktop/mobile
directions and evaluate each with the same rubric:

| Criterion | Review question | Evidence expected |
| --- | --- | --- |
| Task clarity | Can a learner identify the next safe action in ready and recovery states? | paired frames + comprehension notes |
| Behavioral fidelity | Does the frame match the matrix’s canonical and presentation state? | state-to-frame mapping |
| Recovery quality | Are retry, expiry, offline, lock, partial, processing, and conflict actions clear? | injected-state frames |
| Accessibility | Are labels, focus, contrast, target size, reflow, captions, and non-color status feasible? | component review + browser tests |
| Responsive coherence | Does desktop rail/mobile bottom nav preserve the same job without overflow? | 390px/desktop paired frames |
| Extensibility | Can future program/activity variants fit without new semantics? | component/slot review |
| Implementation risk | Are assets, APIs, provider gates, and async states explicit? | risk log and source references |

The reviewer must record direction IDs, source assets, independent scores,
trade-offs, selection/rejection, and superseded references in
`05-handoff-qa/decision-log.md` and `asset-manifest.json`. “Selected” and
“approved” are separate: selection is a design decision; production approval
requires exact implementation evidence.
