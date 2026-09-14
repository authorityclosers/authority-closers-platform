# Personal report voice and overview polish

Base application release: `c437c1758d8a66ede0221f83fe787bb13de33c40`.
This follow-up is isolated from the release operator's current VPS activation.

## Owner acceptance

- Address the closer directly with `you`/`your`, using plain coaching language.
  Preserve source quotations, speaker labels, buyer facts and uncertain attribution.
- Remove the prominent source-moment/finding/dimension/next-step counters and
  the prominent unreviewed-draft badge from the report header.
- Lead with useful, supported qualitative skill observations when available;
  otherwise begin with strengths and priority improvements. Do not turn missing
  measurements into zero scores or invent qualities, ratings or percentages.
- Improve the existing AC overview with decorative SVGs and restrained motion,
  while preserving source seeking, keyboard access, printing, mobile layouts,
  English controls and mixed-script content.
- Keep actual source/review provenance available within Report details. The
  design does not imply Dipak personally reviewed an automated report.

## Implementation and checkpoint boundary

The shared C5 prompt now includes `REPORT_VOICE: direct-coaching-v1`. Both
configured Groq and Gemini task envelopes receive it. It changes the coaching
input hash, while the source/transcript/profile revisions and approved output
limit remain unchanged. C2 transcription and C4 fact inputs remain identical.
Existing saved reports and audit records are not rewritten by this presentation
change; generating new coaching requires the usual source-bound quote/reservation.

The 95 actual / 100 declared weight discrepancy remains held. A skill observation
is not a grade or an approved assessment of a person's fixed traits.

## Verification so far

- Prompt/report/task tests: 82 passed in 3.65 seconds; actual JUnit receipt at
  `D:/AC-authority-closers-release-audit/personal-report-20260914/prompt-tests-final.xml`.
- Earlier run: 51 passed, 1 failed because the new test used an unsupported Gemini
  model ID. The corrected test uses the repository's supported Gemini 3.8 route.
  No provider or budget restriction was relaxed.
- Ruff check and format check passed for the changed Python prompt and unit tests.
- Dependencies installed from the frozen lockfile entirely offline: 399 reused,
  zero downloaded, no dependency version changes.
- Final complete Sales web suite: 127 tests across 17 files passed, 15.64 seconds.
  JUnit: `D:/AC-authority-closers-release-audit/personal-report-20260914/ui-tests-final.xml`.
- Optimized Next static build and its TypeScript phase passed. Actual output:
  `D:/AC-authority-closers-release-audit/personal-report-20260914/build-final.log`.
- Independent Luna reviews found an incorrect advertised-limit fallback and an
  ethics-note visibility regression. Both were fixed and independently re-reviewed;
  no new scoped issue remained. The separate LMS client was not proven to bypass
  entitlements and is not reported as a security exploit.
- Built-browser verification used the real public acquisition route and the
  authenticated CallStudio presentation with explicit synthetic HTTP fixtures.
  Source seeking began at 1.0 seconds and played; the browser stopped the selected
  1.0–2.2-second excerpt on its next timeupdate. Original mixed-script transcript
  lines remained unchanged. Keyboard ArrowRight selected and focused Sales factors.
- Browser checks confirm removed counters, collapsed review details, supported-only
  skill observations, ethics notes without assessed skills, confirmed 99m55s,
  an expired-session unknown balance and an exhausted 0m00s balance.
- 320px and 390px viewports had no document horizontal overflow. Reduced-motion
  preference disabled overview animation; happy-path console warning/error captures
  were empty. Screenshot/JSON/network receipts live beside the JUnit under
  `browser-final.json`, `public-overview-final.png`, `public-mobile-320-final.png`,
  `public-mobile-390-final.png`, `supported-skill-overview-final.png` and
  `presentation-network.jsonl`.
- Print-media checks exposed all report panels and hid the audio layout. This
  in-app browser reports that printing is unavailable, so no PDF export is claimed
  here. This presentation fixture does not prove hosted authentication, provider
  report quality, live deletion or production campaign capacity.
- No provider call was made for this change. Integration, final release CI and
  authenticated live acceptance belong to the next release and remain pending.

## Campaign controls follow-up

The owner also requested visible remaining minutes and a cost analysis for
100 students within INR10,000. Quota/identity/abuse enforcement is being checked
separately against current source and runtime evidence. This note does not change
business allotments, authorize spending, claim VPN blocking, or expand the current
runtime budget.
