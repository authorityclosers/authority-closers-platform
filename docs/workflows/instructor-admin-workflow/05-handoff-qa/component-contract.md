# Component and token contract


This is an implementation handoff contract, not a component library or app
code. IDs are from the controlled UI System. A component is `reference-ready`
when its semantic role is clear; it is not production-approved until the
actual implementation passes accessibility and route/state tests.

## Shell and navigation

| UI ID | Use in package | Required behavior | Status |
| --- | --- | --- | --- |
| `UI-C001` AppShell | Admin host frame | Distinguish Admin from learner product; announce route and session/context safely | reference-ready |
| `UI-C004` SideNav | Wide Admin navigation | Keyboard reachable; capability-aware; no new route implied by a label | reference-ready |
| `UI-C005` Breadcrumbs | Registered content/person routes | Expose current object/version without leaking denied resources | reference-ready |
| `UI-C006` PageHeader | Every non-blocked screen | Title, scope/freshness and safe next action | reference-ready |
| `UI-C014` StatusBadge | Version/lifecycle and state labels | Text plus shape/icon; never color alone | reference-ready |
| `UI-C017` Button / `UI-C018` IconButton | Mutations and compact actions | Server capability controls visibility; disabled is not the only denial treatment | reference-ready |
| `UI-C019` Menu / `UI-C020` Tabs | Secondary navigation | Predictable keyboard order and focus | reference-ready |

## State, form and recovery

| UI ID | Use in package | Required behavior | Status |
| --- | --- | --- | --- |
| `UI-C022` Dialog | Discard/correction/publish confirmation | Focus trap/restore; clear consequence; reason where required | reference-ready |
| `UI-C023` Drawer | Compact detail/filter/recovery context | Do not hide required status or focus order | reference-ready |
| `UI-C024` Toast | Supplemental result cue | Never sole source of outcome or audit reference | reference-ready |
| `UI-C025` InlineAlert | Validation, blocked, stale and recovery state | Named status, non-color signal, actionable recovery | reference-ready |
| `UI-C026` EmptyState | Valid no-record query | Explain condition; no fake counts | reference-ready |
| `UI-C027` Skeleton / `UI-C028` Spinner | Loading/processing | Accessible named status; preserve input | reference-ready |
| `UI-C029` TextField / `UI-C031` Select / `UI-C032` Combobox | Search and content draft fields | Persistent labels, errors, autocomplete semantics and focus preservation | reference-ready |
| `UI-C037` FileUpload / `UI-C038` Dropzone | Course-media draft dependency only | Provider-neutral lifecycle; no real-call activation; limits blocked | blocked by `BLK-06`/`BLK-08` |
| `UI-C039` SearchField / `UI-C040` Pagination | People and catalog lists | Preserve query across states; announce result context without counts not returned | reference-ready |
| `UI-C042` FilterBar / `UI-C043` BulkActionBar | Filters and future bounded bulk action | Preview/audit; partial semantics blocked | `BLK-11` for bulk |
| `UI-C044` Stepper | Compact content editor/publish context | Same semantics as wide panes; no alternate workflow | reference-ready |
| `UI-C045` Timeline | Person/evidence/recovery history | Chronological, text-labeled, immutable history markers | reference-ready |

## Domain-specific reference components

| UI ID | Use | Guardrail | Status |
| --- | --- | --- | --- |
| `UI-C041` DataTable | Wide people/program lists | Reflow to cards/stacks below wide breakpoint; no horizontal-only mobile | reference-ready |
| `UI-C047` VideoPlayerShell / `UI-C048` TranscriptPanel / `UI-C049` ResourceList | Course content references | Media readiness is source-backed; provider behavior is not invented | `BLK-08` for provider specifics |
| `UI-C050` QuizQuestion / `UI-C051` AttemptSummary | Assessment reference only | No fake schema, attempt limit or score class | `BLK-07` |
| `UI-C052` RubricScorecard / `UI-C053` EvidenceQuote / `UI-C054` FeedbackPanel | Human review reference only | Human-confirmed official boundary; preserve evidence lineage | `BLK-05`/`BLK-07` |
| `UI-C055` CallUploadStatus | Real-call seam only | No real recording/transcription/external AI in this package | `BLK-06` |
| `UI-C062` AuditTimeline | Candidate audit route | Restricted/masked/exportable only when contract grants it | `BLK-09`/`BLK-12` |
| `UI-C063` PermissionMatrix | Future role review | Display existing server contract only; no Instructor union | `BLK-01` |
| `UI-C064` ConfirmationPanel | Publish/correction/recovery | Consequence, reason, idempotency and reference are explicit | reference-ready |
| `UI-C065` ErrorBoundary / `UI-C066` OfflineBanner | Fault/stale state | Preserve context; no false sync | reference-ready |
| `UI-C067` SupportReference | Layered recovery handoff | Mask sensitive context and identify owner/reference | `BLK-12` for exact masking |
| `UI-C068` ChartContainer / `UI-C069` KPITrend / `UI-C070` CohortTable | Future descriptive reporting | No invented values; analytics cannot become canonical state | `BLK-04` |

## Semantic token contract

Use semantic tokens from the UI System. Brand mapping is intentionally absent.

| Token family | Package contract |
| --- | --- |
| `color.brand.*` | `TBD`; no hex values or font-brand claims |
| `color.surface.*`, `color.text.*`, `color.border.*` | Use contrast-checked semantic roles; status is also text/icon/shape |
| `color.success`, `warning`, `danger`, `info` | State cues only; never sole status signal |
| `space.0..12` | 4px-based spacing scale; density may tighten in Admin without hiding context |
| `radius.*`, `shadow.*`, `z.*` | Use system values; do not create a decorative visual language here |
| `font.*`, `type.xs..4xl` | Semantic scale only; actual family/brand mapping is blocked |
| `motion.fast/base/slow` | Respect reduced-motion preference; do not animate required status away |

## Responsive/a11y acceptance

- Compact `<600px`: stack records, use Stepper/Drawer where it preserves
  context, and avoid horizontal-only tables.
- Medium `600–1023px`: reflow columns and keep the same action hierarchy.
- Wide `>=1024px`, dense Admin `>=1280px`: allow navigation rail and editor
  panes with clear reading order.
- Keyboard: skip target, visible focus, logical tab order, focus after
  route/error/dialog/async result.
- Touch/zoom: 44pt/48dp minimum target guidance; reflow/zoom without clipped
  state or lost draft.
- Screen readers: labels for inputs/table rows, named live status, error
  summary and text status in addition to color/icon.
