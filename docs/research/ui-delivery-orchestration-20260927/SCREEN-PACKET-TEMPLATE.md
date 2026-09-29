# Bounded screen packet

Candidate template for a future authorized implementation task. This file is not an instruction to implement now. Resolve current source/data contracts and required controlled-document reads before first-slice code. The references establish visual intent, not that every pictured capability exists.

```yaml
id: report-overview-01
status: prepared-not-implemented
source_revision: e488f952b1aafc10761f304630965d8233a2e39b
working_tree_delta: record hashes/diff before dispatch; HEAD alone is insufficient
objective: Understand the saved call, identify one priority and open its evidence
reference_family: existing Drive library only
references:
  desktop: images/06-report/06-report-01-overview-desktop.png
  mobile: images/06-report/06-report-01-overview-mobile.png
  corrections: resolve relevant original review findings before coding
reference_manifest: INPUTS.json
css_viewport_mapping: determine from intended content frame; raster pixels are not CSS pixels
writer: one named agent
reviewer: fresh read-only agent
allowed_files: enumerate after current source inspection
excluded_files: other screen routes and global tokens unless explicitly assigned
shared_component_revision: record accepted shell/player/token revision
data_contracts: exact current route/schema/source references; no inferred scores or saved-state claims
fixture: synthetic data, stable IDs/time, English and Marathi variants
states: [loaded, loading, empty, partial, recoverable-error, keyboard, overlay-open, reduced-motion]
actions: [play-pause, evidence-open, return-to-position, tab-change, overflow-menu]
required_evidence: [diff, viewport-captures, full-page-captures, behavior-results, discrepancy-log]
done: required states and actions pass; independent review resolved; coordinator receipt saved
```

Give the writer: this completed packet, the two actual images, short design tokens/component API, relevant source files and the prior discrepancy list. Do not supply the whole image library.

Writer prompt:

> Implement this one screen family in the existing app, preserving the selected references and real contracts. Own only the listed files. Inspect images before editing. Match hierarchy, density, typography, geometry and responsive behavior. Complete the listed actions and states. Run the scoped checks and supply actual captures. Do not update approved screenshot baselines or mark yourself accepted. Report remaining differences and the exact revision. If the packet conflicts with a real contract, identify the conflict and continue independent safe work.

Reviewer prompt:

> You are read-only. Compare reference and rendered captures at the declared content frame and scale. Attempt the critical task using the supplied browser evidence. Return a short list of concrete visual and behavioral defects, each with location, expected result, severity and evidence. Treat missing evidence as unverified. Do not restyle the product, invent features, waive a failed check or accept an arbitrary image-diff percentage. Return pass or rework for the stated scope.

Luna helper prompt:

> Inspect only the named fixture/test/source paths. Map each required state/action to an existing check or a specific missing assertion. Return a compact coverage table and exact file references. Do not start a server, install dependencies, edit product files, spawn agents or make provider calls. A separate owner runs the one authorized test job.

Receipt fields:

```yaml
screen_id: ...
implementation_revision: ...
input_manifest_sha256: ...
model_and_effort: actual resolved values
writer_files: []
tests: [{command: ..., environment: ..., result: ..., evidence_path: ...}]
captures: [{viewport_css: ..., dpr: ..., browser: ..., locale: ..., motion: ..., path: ..., sha256: ...}]
reference_comparison: accepted|rework|unverified
behavior_result: accepted|rework|unverified
deviations: []
usage: {tokens: unknown, subscription_delta: unknown, settled_cash: unknown}
accepted_by: coordinator identity and evidence; user decision only if needed
staging_verification: unverified
```

Store secrets/auth state outside the packet. The selected reference's fictional call details are illustrative, not production test data or proof of a supported capability.
