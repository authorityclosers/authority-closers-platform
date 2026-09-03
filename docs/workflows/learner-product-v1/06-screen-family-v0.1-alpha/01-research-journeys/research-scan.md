# Research scan

This scan separates controlled facts, observations, hypotheses, and design
inferences. It is not a new business decision. Exact source IDs and Drive URLs
are in [`source-manifest.csv`](source-manifest.csv).

| ID | Evidence type | Finding | Confidence | Severity/frequency hypothesis | Design move / verification |
| --- | --- | --- | --- | --- | --- |
| RS-LSF-01 | controlled fact | Learners are mobile-heavy, time-poor, and outcome-driven; a clear next action outperforms an undifferentiated dashboard hypothesis. | high for persona; medium for outcome hypothesis | high frequency; high activation impact | Make one start/resume/continue action dominant on `HOME-01`; measure first-action comprehension and time to first value. |
| RS-LSF-02 | controlled fact | Dashboard and My Learning are distinct jobs/routes. | high | high frequency; high navigation impact | Keep `HOME-01` orientation separate from `LEARN-01` library/filter tasks. |
| RS-LSF-03 | controlled fact | Published program preview is read-only; explicit free enrollment is authenticated and server-owned. | high | high severity if violated | Keep `COURSE-01` read-only; route start through `HOME-01` and controlled command. |
| RS-LSF-04 | controlled fact | Program/module/activity hierarchy and prerequisite rules are canonical; route possession does not grant access. | high | high severity for privacy/access | Show safe lock/denied reasons and never load unauthorized payloads. |
| RS-LSF-05 | controlled fact | Progress, completion, and evidence are canonical server state; analytics and UI state are secondary. | high | high severity for trust/data integrity | `PROG-01` reads canonical projection; `INSIGHT-01` labels descriptive, stale, or missing data. |
| RS-LSF-06 | controlled fact | Watch evidence is unique server-authoritative intervals under a versioned policy; 90% is a provisional participation default, not mastery. | high | high severity if UI claims mastery or false completion | `ACT-01`/`MEDIA-01` expose evidence status, not a mastery score; provider/assets remain gated. |
| RS-LSF-07 | controlled fact | AC-UXA-01 requires per-activity recovery, support ownership below founder level, captions/alternatives, status announcements, focus, target size, and non-color state. | high | high frequency on poor networks/mobile; P0/P1 impact | Add explicit save/offline/expiry/partial/error rows and QA injections before cohort. |
| RS-LSF-08 | controlled fact | Light is default; Dark/System are device-local presentation preferences and do not sync to account/tenant. | high | medium frequency; trust impact if state crosses users | `SET-02` is local-only with System signal and storage fallback. |
| RS-LSF-09 | controlled fact | PWA/web is first; native bridges and store policy are later seams. | high | medium frequency; release impact | Keep responsive web semantics; do not add native-only claims or store flows. |
| RS-LSF-10 | controlled fact | Certificate is a course-completion artifact distinct from competency certification/official credential. | high | high severity if wording misleads | `CERT-01` uses explicit artifact wording and incomplete/processing/issued states. |
| RS-LSF-11 | design hypothesis | Today/Week/Month containers help a learner orient if they are sourced by a canonical plan projection or explicit learner intent. | low until measured | unknown frequency; medium cognitive-load impact | Provide empty/unavailable/stale states and measure “what is next?” comprehension; never invent dates/cadence. |
| RS-LSF-12 | design inference | A private avatar crop preview reduces accidental replacement and clarifies a provider-gated mutation. | medium | occasional frequency; medium trust impact | Keep old avatar current until success; test cancel/retry/expiry and supersession copy. |
| RS-LSF-13 | design inference | A notification center is useful when read state and deep-link ownership are explicit. | low/medium | unknown frequency; medium interruption impact | Separate notification state from delivery preference/consent; test expired targets. |
| RS-LSF-14 | external normative guidance | WCAG 2.2 target-size, focus, reflow, and status requirements should be tested directly; AC’s comfortable target is larger where practical. | high | high frequency across all screens | Include keyboard, focus-not-obscured, 200% zoom, target-size, text-equivalent, and non-color checks. |
| RS-LSF-15 | external platform guidance | `prefers-color-scheme` and `color-scheme` describe environment preference and browser chrome; System should follow the signal without first-paint flash. | high | medium frequency; visible trust impact | Test Light/Dark/System, storage failure, forced/high-contrast, and safe fallback. |

## Research limitations

- No new cohort, usability session, analytics export, or production telemetry
  was collected for this package. Frequency and severity entries marked as
  hypotheses must be measured in the controlled cohort.
- Controlled sources may describe future paid, B2B, AI, call, or native
  capability; this screen-family package does not activate those capabilities.
- Visual generation and exact-current browser/device evidence are pending.
