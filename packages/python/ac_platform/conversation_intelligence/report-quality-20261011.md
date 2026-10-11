# Retained Report structure check, 11 October 2026

This is a local structural diagnostic of today's account projection and browser
model, not an expert quality verdict, a fresh dev inference, an AC-SVAL pass or
a latency measurement. No provider call or data write was made. Live prompts,
packs, routes, native inputs and activation approvals remain unchanged.

The B/G corpus has **13 finished reports**, comprising 11 real/presumed-real
calls and two fictional calls. **156 counts rendered sections**, from six
sections in both account and guest views; it is not 156 independent reports.
Three corpus entries have no C5. All 13 finished reports predate native pillars
and call maps. Only the full account view is measured here: guest limits must
not count as missing AI content.

## Six sections

Counts below use the 11 real/presumed-real reports. Including the two fictional
reports produces the same empty/thin/generic/script-flag counts. There are no
whole-section semantic quality claims in this table.

| Report section | Empty | Thin | Generic | Prose script flags | English interface labels for an Indic report target |
| --- | ---: | ---: | ---: | ---: | ---: |
| The Big Picture | 0 | 0 | 0 | 0 | 2 |
| How the Call Played Out | 1 | 0 | 0 | 2 | 2 |
| What Worked & What Didn't | 0 | 0 | 0 | 1 | 2 |
| Moments That Mattered | 0 | 0 | 0 | 2 | 2 |
| Your Skills on This Call | 0 | 0 | 0 | 2 | 2 |
| Where the Deal Stands | 0 | 0 | 0 | 1 | 2 |

Definitions: empty = zero narrative units (measured audio metrics do not fill a
missing conversation narrative); thin = exactly one narrative unit; generic =
a nonempty section with zero quote references. These are coarse structural
rules, not a test that a sentence is useful. A section with several fields can
still contain generic subfields: all 13 summaries have no summary citation, and
each deal section has two uncited recommendation/mission units. Uncited
suggestions stay suggestions; they must not become agreements.

Prose script flags count English-only prose with a declared Indic target, or
Devanagari prose with an English target, after excluding verbatim speech. They
are **review candidates**, not adjudicated wrong-language counts: inline quoted
fragments and approved sales vocabulary need human review. Retained metadata
records 11 English targets, one `hi-Deva+en` and one `mr-Deva+en`. Generated
Hindi/Marathi prose permits familiar English sales terms. JSON keys, enums and
identifiers stay unchanged. Source quotations stay in their original language.
English interface headings on the two Indic-target reports are a separate,
confirmed localisation gap, owned by the browser/Document maintainers.

## Language split

Language cohorts use the existing corpus metadata, not a new inference from
Devanagari. Hindi and Marathi cannot be distinguished by script alone.

| Source-language cohort | Finished reports | Fictional | Empty narrative sections | Prose script flags, by section | Sections containing Devanagari quotes |
| --- | ---: | ---: | ---: | --- | ---: |
| Hindi | 2 | 0 | 0 | none | 12/12 |
| Marathi | 4 | 0 | 0 | flow 2; moments 2; skills 2; deal 1 | 24/24 |
| Hindi + English | 1 | 0 | 0 | worked/didn't 1 | 6/6 |
| Marathi + English | 2 | 0 | 1 | none | 11/12 |
| Mixed Indic + English, unverified | 1 | 0 | 0 | none | 6/6 |
| English | 3 | 2 | 0 | none | 1/18 |

Mixed quotation script is preserved, not translated or labelled an error.
The English cohort's one Devanagari-bearing section is still source-bound;
source language does not prescribe the report language. No provider speaker-ID
leaks were detected in model prose. These old reports have no call-map spoken
name fields; names and confirmed role choices from the separate speaker-map
endpoint were not audited or inferred here.

## Five main patterns

| Pattern | Reports, all 13 | Real/presumed, 11 | Anonymised shape only |
| --- | ---: | ---: | --- |
| Summary has no own citation | 13 | 11 | `summary: string; summary_evidence: absent` |
| Timeline absent in saved source | 13 | 11 | `call_map: absent; flow.phases: null` |
| No commitment or dated next-event fields | 13 | 11 | `prospectCommitments: []; sellerCommitments: []; nextEvent: null` |
| Discovery-clear and presentation depth absent | 13 | 11 | `discovery.clear: []; presentation: absent` |
| Analyst words remain in generated prose | 11 | 9 | `observation: [analyst verb] + [action]`, rather than an everyday sentence |

The last pattern uses the private sweep's bounded word list and prose traversal;
it is not interchangeable with G's Word-document occurrence count. Six of 13
summaries also fall outside the three-to-five-sentence shape, and one saved
before/after value equals a literal quote rather than a summary.

## Mapping checks and handoffs

The account projection preserves **all 720 evidence occurrences** from saved
reports. It contains 752 occurrences because `next_action` duplicates an
existing improvement; none is lost. Browser direct-report and account-projection
models are equal on all 13 inputs. Rendered quotes have zero text/timing binding
failures. The 39 private corpus files and eight source files stayed unchanged
through the run. No Python parser/projector repair was justified by this sample.

Two browser defects found by source review were sent as exact requests to B,
without editing B's files:

1. `report-story-model.ts`, `withPillars`: a matching pillar summary replaces
   its bound base summary with `sources: []`. Keep the base refs when the texts
   match; unrelated legacy optional summaries must not borrow those refs.
2. `report-story-model.ts`, `reportStoryModel`: assigned `prospect_tasks` are
   concatenated into `deal.prospectCommitments`. The Python story deliberately
   separates tasks from agreement. Keep only actual `prospect_commitments` in
   that list. Neither defect is counted as an observed retained-corpus failure:
   these inputs have no pillars or call-map tasks.

B/G also own language-sensitive interface labels. The retained C5/account
content lacks a report-language key in all 13 cases, so these results use the
separate corpus manifest's target only. Any product language tag must come from
the source-bound processing plan, not transcript-script detection or guessed
names. Do not add an unknown key to the strict legacy `story` envelope.

After Gate 2, use the same pinned calls to compare the v8 candidate's summary
citations, timeline, roles, genuine commitments, deeper fields, and plain
language. Missing source content must stay an honest gap until that approved
output exists; no parser should invent it.

## Reproduction and source pins

Private harness and count-only receipt are at
`/home/acdev/strikes/1801/quality-sweep-20261011/`. Run locally in the web app:

```sh
SWEEP_RECEIPT=<new-private-receipt-path> ac-heavy node node_modules/vitest/vitest.mjs run \
  --config /home/acdev/strikes/1801/quality-sweep-20261011/vitest.config.mjs --reporter=verbose
```

The first sweep passed in 10.67 seconds after waiting for the shared slot;
the final sweep plus five fictional diagnostic guards passed (six tests) in
7.89 seconds. Both runs have identical source and input-set pins. Head was
`67e74ea29720b25d6b218635aa4720a972681fb9`; the following exact source hashes,
not unrelated concurrent workbench commits, bind the claims:

| Source | SHA256 |
| --- | --- |
| Python report access | `c6ffceefb14b50d42ef4d510e19dc2e4ddf37fe6648ad7e5940ebb8e5051d32a` |
| Python reports parser | `a96b185718f7e834e20b6399f865521539aaf8aac73c5532283085dbb2ed68ba` |
| Python story projection | `d2052ae785425df00d97ff2e4c810da2a07433422ec9aae37271aec215fcfb7d` |
| Browser report contract | `ca3f99f8c07eca115e3793bebb23c052984e50ab5d93ccce20674503ce6c687e` |
| Browser story model | `5cdd7f8225bde880eaa5bf72b2ce1b561fb0095172b8713ecf05951fc0456157` |
| Browser pillars contract | `5a7d42486c3cbda4a9a3b9a2125f8ccc957b2df86e5769e14ce83a53b74b7ce6` |
| Browser Document model | `20e84e8333a418c2477b32e31587b714987c28e735e2416b8873c49dcd08a38b` |
| Browser copy | `5433fae17169a44dfdef5eed40f13ba17f50ae5947573ea03180b91b1e2bbf21` |

Private input-set digest (39 files):
`2e05373fc537d63c152d39d3edfd1563993af5238948ae84ed0ed2a1ce04e630`.
Only counts, structural shapes and hashes are retained in this document. No
customer text, quote, name or raw output is copied into Git or shared notes.

Final private count-only receipt SHA256:
`1bfe1e1fa75d83cc10d0b370ac760a8e6eb865276ec8b5659e8cf5fd6ad162ac`.
Dev API health is 200 at `28cd3de229e0af0a5146103468ab3ddeea02e60b`;
all three Python source pins above match that serving Git source (22:41 UTC).
No authenticated hosted Report was read by this session.
