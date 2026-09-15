# Gemini 3.1 Pro C4 profile preparation

The source-owned preparer at
`scripts/prepare_gemini31_provider_profile.py` creates an offline candidate
from an existing registry and its matching pinned approval. It adds one exact
provider binding and one finite acquisition profile:

| Stage | Provider and model | Per-request ceiling |
| --- | --- | ---: |
| C2 | ElevenLabs `scribe_v2` | ₹11 |
| C4 | Gemini `gemini-3.1-pro-preview` | ₹7 |
| C5 | Gemini `gemini-3.8-flash` | ₹5 |

The Pro facts route uses the existing Gemini credential, provider terms,
privacy, endpoint approval, retention and professional references. It has a
new pricing reference and evidence hash. Coaching stays on the existing Flash
route because the source adapter gives Pro the conservative 8,000-token prompt
budget while Flash coaching has the 32,000-token budget.

Google's official pricing page lists Gemini 3.1 Pro Preview Standard pricing at
$2 per million input tokens and $12 per million output tokens for prompts up to
200,000 tokens: [Gemini Developer API pricing](https://ai.google.dev/gemini-api/docs/pricing#gemini-31-pro-preview).
The native adapter admits this route up to 19,416 UTF-8 input bytes when its
existing `ceil(input_bytes / 3) + output + 128 <= 8,000` gate is applied. The
financial bound deliberately treats every admitted UTF-8 byte as one input
token, then adds 128 fixed system-prefix tokens and 1,400 output tokens. At the
planning conversion of ₹100/USD, this computes to 559 paise and rounds the
stage ceiling to 700 paise. The one-byte/one-token rule is a conservative
accounting bound, not a provider tokenizer claim. This is planning evidence
only; it does not establish account funding, quota or a successful provider
call.

The generated candidate was prepared from release `0847db5d3ca1ed825b68c226713d0f52d11683b1`:

| Environment | Alternate config digest | Candidate approval digest | Budget scope | Projected plan cap |
| --- | --- | --- | --- | ---: |
| staging | `91dcd7426c56f493f3a17717bf03dea4fd6965752201861e1031ce327d7c70ba` | `3bf47217788668e2a9fbcd8482fdd1d9d944a561f5cef700eb9029512b3f3f8a` | `11620b74-7e36-4f8a-8e4c-faf336c42888` | ₹93 |
| production | `649ec42fc55bfc60d662fa74904bd4bc29603495f3270662dc3112cb7dbbb0f3` | `61ca8643d3f0ac6081ce92e4b32f5019fbe19159ec98acab5f27503d5fb7d8a7` | `9771c532-f96f-4547-bc74-400fa41733ba` | ₹464 |

The existing caps remain ₹100 staging and ₹900 production. Candidate files are
in the external audit directory:

`D:\AC-authority-closers-release-audit\activation-20260914\prepared-gemini31-profile-94d670f\`

Both candidate bundles are marked `candidate_pending_owner_approval`. They are
not activated, and the preparer records that no provider calls, database
writes, runtime mutations or secrets were involved. The current release's
default approval bytes and budget identities remain unchanged. The staging
candidate's ₹93 maximum plan exceeds the currently observed ₹74 available test
budget, so staging must wait for a source-backed budget reconciliation or a new
approved hold; do not activate it against the current available balance.
Production's ₹464 maximum remains below its ₹900 cap, subject to the same live
availability and hold recheck. A release owner must approve the new Pro
pricing/provider route, produce the new pinned bundle, save the alternate
registry revision through Admin, and activate it with the existing idempotent
activation command before it can appear as an Admin option.

Validation:

- preparer unit tests: `2 passed`;
- focused activation/profile/legacy-snapshot tests: `49 passed`;
- preparer and test Ruff checks: passed;
- both staging and production candidate manifests generated offline from the
  matching pinned registry and approval digests; the regenerated manifests
  record the ₹7 Pro C4 ceiling and safe UTF-8 billing bound.
