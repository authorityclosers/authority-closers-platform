# C5 processing-plan request budget repair

CI run 34874044049 at `1b1f0159feacb0a224a10ccf9fe25b8341c504a6`
failed report progression and browser quotation while 5664 Python tests passed.
The report prompt fit the older 1800-token output allocation, but the durable
plan uses 3200 tokens. A default-profile, one-fact reproduction required 8162
conservative units against the existing 8000-unit Groq limit (6762 at 1800).

This change compacts repeated C5 instructions. It preserves the frozen profile,
all observations, evidence, uncertainty and coverage fields, root-type guidance,
all overview fields, direct coaching voice, source attribution and qualitative
constraints. It changes no budget constant, output cap, provider selection,
price reservation, response parser or checkpoint. Request hashes change because
the system wording changes; saved C2/C4 remain reusable.

## Tested here

- 174 focused unit tests passed, including six new one-/three-fact cases at the
  actual 3200 output allocation across Groq and both supported Gemini routes.
  Preparation and reconstruction preserve all supplied facts and profile data.
- Three previously failing PostgreSQL tests passed using the existing disposable
  loopback database and unique schemas: exhausted-minute progression, exact
  acceptance bindings and the composed worker reaching private C6.
- Both previously failing real Chromium tests passed over real loopback HTTP and
  PostgreSQL: hosted authority C2/C4/C5 plus saved-report reuse, and explicit
  processing-plan progression without duplicate provider execution.
- Browser/provider results in these tests are synthetic; no external inference,
  paid call or production database write was made by this change.

External receipts are retained under
`D:/AC-authority-closers-release-audit/`:

- `peer-c5-compact-focused-final3-20260914.log` and `.xml`: 174 passed.
- `peer-c5-compact-pg-20260914.log` and `.xml`: 3 passed in 42.76 seconds.
- `peer-c5-compact-e2e-20260914.log` and `.xml`: 2 passed in 53.78 seconds.
- `peer-c5-compact-browser-authority-20260914.json` and
  `peer-c5-compact-browser-plan-20260914/`: browser/network receipts.
- `peer-c5-compact-full-call-proof-final-20260914.json`: read-only preparation
  and reconstruction of the retained 152-segment, four-packet, 38-observation
  production input, preserving native evidence and its frozen profile.

Hosted CI, deployment and the actual model-generated production report still
require their own receipts. Input admissibility does not establish output
quality or semantic completeness of the earlier fact extraction.
