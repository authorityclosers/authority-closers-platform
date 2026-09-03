# Responsive reference wireframes


These are low-fidelity text compositions. They are not screenshots, branded
mockups or production approval. Every label that is not a controlled module
name is a design inference and must be checked against the state matrix.

## Wide Admin overview — `ADM-OVERVIEW` (`>=1280px`)

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ AC Admin  [Skip to content]                         session/context  [profile] │
├──────────────┬───────────────────────────────────────────────────────────────┤
│ Overview     │ Overview                                                      │
│ People       │ scope / freshness: [returned by read model]                   │
│ Catalog      │                                                               │
│ Learning Ops │ ┌──────────────┐ ┌──────────────┐ ┌────────────────────────┐ │
│ Assessments* │ │ module link  │ │ module link  │ │ capability gate notice │ │
│ Audit*       │ │ source-backed│ │ source-backed│ │ blocked item if gated  │ │
│ System*      │ └──────────────┘ └──────────────┘ └────────────────────────┘ │
│              │                                                               │
│              │ recent references / empty or stale state when supplied        │
│              │ [named status region]                         [Retry]         │
└──────────────┴───────────────────────────────────────────────────────────────┘
* module label may be present in the controlled Admin IA; route is not implied
```

Behavior: the left rail is keyboard reachable and capability-aware. Cards
contain links, not invented metrics. The status region is announced and
remains available after a retry.

## Wide content editor — `INS-CONTENT` (`>=1280px`)

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ AC Admin / Catalog / Program / Content                 version: [source data] │
├──────────────┬──────────────────────┬────────────────────────────────────────┤
│ Program      │ Program              │ Validation / version / audit context   │
│ ├ Module     │ [draft or read state] │ [draft|in review|published|conflict]  │
│ │ ├ Activity │ editor sections      │ dependency status (source-backed)     │
│ └ ...        │ [preserved input]    │ [Save draft] [Validate]                 │
│              │                      │ [Request action if server grants]     │
│              │                      │ named error/status + recovery          │
└──────────────┴──────────────────────┴────────────────────────────────────────┘
```

The tree does not expose permission that the server did not grant. Published
versions render immutable markers. The right panel must not invent assessment
fields, audience, provider limits or billing impact.

## Wide people/progress detail — `ADM-USERS` → `ADM-USER-DETAIL`

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ People / search and filters                              [freshness status]   │
├──────────────────────────────────────────────────────────────────────────────┤
│ search [                                 ]  filters [ ]                       │
│ ┌──────────────────────────────────────────────────────────────────────────┐ │
│ │ authorized person record / version and context / open detail              │ │
│ │ authorized person record / version and context / open detail              │ │
│ └──────────────────────────────────────────────────────────────────────────┘ │
├──────────────────────────────────────────────────────────────────────────────┤
│ Person detail: non-sensitive context | enrollment | progress | evidence      │
│ history / support reference / reconciliation owner (only if returned)       │
│ [inspect] [safe recovery if granted] [reason + confirmation for correction]  │
└──────────────────────────────────────────────────────────────────────────────┘
```

No learner count, payment status or analytics-derived completion is placed in
the layout by default.

## Compact Admin list — `ADM-USERS` (`<600px`)

```text
┌──────────────────────────────┐
│ AC Admin       [menu]        │
│ People                        │
│ [Search people        ]       │
│ [Filters] [freshness]        │
├──────────────────────────────┤
│ person record                 │
│ context / version             │
│ [Open detail]                 │
├──────────────────────────────┤
│ person record                 │
│ context / version             │
│ [Open detail]                 │
├──────────────────────────────┤
│ [pagination or load status]   │
└──────────────────────────────┘
```

The compact layout reflows records instead of horizontally scrolling a dense
table. Search/filter input survives loading, denied, stale and retryable
states. Touch targets follow the 44pt/48dp guidance; the menu has a visible
focus order.

## Compact content editor — `INS-CONTENT` (`<600px`)

```text
┌──────────────────────────────┐
│ AC Admin / Catalog    [back]  │
│ Program content              │
│ Step 1 Tree  2 Edit  3 Check │
├──────────────────────────────┤
│ version/status badge          │
│ current step content         │
│ preserved draft fields       │
│ field/dependency errors      │
│ named async/provider status  │
├──────────────────────────────┤
│ [Back]              [Next]   │
│ [Save draft]                  │
└──────────────────────────────┘
```

The Stepper is a responsive representation of the same semantic sections as
the desktop tree/editor/validation panes. It must not introduce a different
publication workflow. If the assessment or provider contract is absent, the
current step is an explicit `blocked` state with a reason and no fake control.

## State treatments

| State | Visual treatment | Required non-visual behavior |
| --- | --- | --- |
| loading/processing | skeleton or progress region with named status | announce status; preserve route/input |
| empty | explanatory empty panel | no fabricated counts; focus next safe action |
| denied/blocked | high-contrast panel with reason and reference | no resource enumeration; keyboard-reachable return |
| validation_error | summary + field/section markers | focus first error; text and icon, not color alone |
| stale/offline | persistent banner and retry | never claim sync or mutation success |
| conflict/reconciliation | hold banner with version/trace context | stop unsafe retry; offer idempotent recovery/escalation |
| success | inline result + returned reference | announce result; retain an inspectable history link |

## Visual acceptance boundary

This package is ready for content/interaction critique only. It is not a
brand, accessibility or production approval. A future visual pass must use
approved semantic-to-brand tokens, non-sensitive fixtures and the source
matrix as the behavior contract.
