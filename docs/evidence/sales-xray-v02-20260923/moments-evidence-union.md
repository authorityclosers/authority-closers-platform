# Preserve report evidence in Moments

The overview branch previously returned only `overview.rewatch`, even when the
same accepted report contained other linked findings. An empty shortlist hid all
finding excerpts. The private Pro research handoff at
`2467ec241e0b15dbac715781c3d40584ff7ac20a` identified this projection defect; the
application source was independently checked before applying this patch.

Moments now combines the supplied shortlist and the five canonical finding
collections. Exact segment, source-clock range and quote determine an excerpt's
identity. The shortlist remains first, followed by first-seen finding order.
Repeated references share a clip while retaining every original observation.
Category filtering selects that category's title, explanation and playback
reference. Full review and print retain the other linked observations.

There are no new report fields, inferred moments, provider requests or background
fetches. The component only uses the authorized report object passed to it.
Different quotes, segments or source-clock ranges are not merged. Counts describe
distinct supplied excerpts, not independent events, insight quality or scores.

## Validation

- All 39 Sales Xray web test files passed: 355 tests.
- TypeScript typecheck, focused ESLint and `git diff --check` passed.
- New regression cases cover one shortlisted excerpt plus three finding excerpts,
  an empty shortlist, exact duplicate clips with multiple contexts, category and
  playback correctness, print completeness, no mutation of report input, and
  repeated words at different segments/time ranges.
- Existing pagination, keyboard/modal focus, full-text review, empty states,
  transcript search and report-switch tests still pass.

The retained fictional 59:58 baseline has two shortlist references and 33 finding
references; their union contains 24 distinct exact excerpts. This is a data
inventory of the old accepted report, not 24 independent events or a newly
generated report. The behavioral tests use repository-owned synthetic fixtures;
private report/transcript bytes are not added to Git.

This is a local renderer repair. No production deployment or new browser
viewport proof is claimed by these checks. It does not establish that coaching-v4
generates better analysis or that full Brain 3 is implemented.
