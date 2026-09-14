# Gemini 3.1 Pro C4 profile preparation

The source-owned preparer at
`scripts/prepare_gemini31_provider_profile.py` creates an offline candidate
from an existing registry and its matching pinned approval. It adds one exact
provider binding and one finite acquisition profile:

| Stage | Provider and model | Per-request ceiling |
| --- | --- | ---: |
| C2 | ElevenLabs `scribe_v2` | ₹11 |
| C4 | Gemini `gemini-3.1-pro-preview` | ₹3 |
| C5 | Gemini `gemini-3.8-flash` | ₹5 |

The Pro facts route uses the existing Gemini credential, provider terms,
privacy, endpoint approval, retention and professional references. It has a
new pricing reference and evidence hash. Coaching stays on the existing Flash
route because the source adapter gives Pro the conservative 8,000-token prompt
budget while Flash coaching has the 32,000-token budget.

Google's official pricing page lists Gemini 3.1 Pro Preview Standard pricing at
$2 per million input tokens and $12 per million output tokens for prompts up to
200,000 tokens: [Gemini Developer API pricing](https://ai.google.dev/gemini-api/docs/pricing#gemini-31-pro-preview).
The preparer bounds this route to 19,416 UTF-8 input bytes (6,472 conservative
input tokens), 1,400 output tokens and 128 adapter overhead tokens. At the
planning conversion of ₹100/USD, the calculated ceiling is 298 paise and the
quoted stage bound rounds up to 300 paise. This is planning evidence only; it
does not establish account funding, quota or a successful provider call.

The generated candidate was prepared from release `0847db5d3ca1ed825b68c226713d0f52d11683b1`:

| Environment | Alternate config digest | Candidate approval digest | Budget scope | Projected plan cap |
| --- | --- | --- | --- | ---: |
| staging | `7b8038c7ae2c3434a57a1c08109778ff1123debcdc60e99daffc313aea76e54a` | `7239cc89d07a79246ae461796941f6a0a169e13ac7cbcb824c4c1e32db19b62d` | `11620b74-7e36-4f8a-8e4c-faf336c42888` | ₹49 |
| production | `61ee593b6b8efc0d21e7f8c639bed8c6ae3c100921c7a84cb3d49be659e1567f` | `0e6a0b12d0ac6bbda9040e3df8c44ced9b5303fb18f1ba19e2b0ec39311e9f09` | `9771c532-f96f-4547-bc74-400fa41733ba` | ₹208 |

The existing caps remain ₹100 staging and ₹900 production. Candidate files are
in the external audit directory:

`D:\AC-authority-closers-release-audit\activation-20260914\prepared-gemini31-profile-ca12d5b\`

Both candidate bundles are marked `candidate_pending_owner_approval`. They are
not activated, and the preparer records that no provider calls, database
writes, runtime mutations or secrets were involved. The current release's
default approval bytes and budget identities remain unchanged. A release owner
must approve the new Pro pricing/provider route, produce the new pinned bundle,
save the alternate registry revision through Admin, and activate it with the
existing idempotent activation command before it can appear as an Admin option.

Validation:

- preparer unit tests: `2 passed`;
- focused activation/profile/legacy-snapshot tests: `49 passed`;
- preparer and test Ruff checks: passed;
- both staging and production candidate manifests generated offline from the
  matching pinned registry and approval digests.
