# Deepgram C2 alignment implementation evidence

Implementation-only predecessor: `1635260f83fea124786e6103bb8e4db77e4d3378`.
The documented implementation is `608965a912bea5d53d0f9e995836aa28b4b6d3fd`.
The integration release also includes the Admin per-minute pricing fix; its
exact source commit is bound by the successful CI run and deployment receipt.

The alignment contract now recognizes the existing normalized Deepgram
`deepgram-native-seconds` timebase. It retains the fail-closed, honest result:
`provider_native_clock_unmapped_to_decoded_audio_track`, with no certified
timing or speaker/channel attribution. The processing-plan regression starts
from a completed synthetic Deepgram C2 receipt, advances through C3 planning,
queues C4, and asserts the broker was called only once; the fixture never calls
a provider service.

Validation on 2026-09-16:

- Focused unit suite (`test_alignment.py`, `test_inference_tasks.py`, and
  `test_providers.py`): **66 passed**.
- Ruff format/check on all five changed Python files: **passed**.
- Mypy on `alignment.py`: **passed**.
- Compileall and `git diff --check`: **passed**.
- PostgreSQL scheduler regression in the integration tree: **1 passed** on the
  disposable loopback PostgreSQL harness. The identical fixture changes also
  passed all processing-plan (**11**), authority (**7**) and reporting-pipeline
  (**4**) tests in the isolated proof worktree.

The first integration CI attempt failed in synthetic setup, before testing the
continuation: its Deepgram configuration still used the ElevenLabs recipe and
was saved without activation. The fixture now selects the provider's recipe
and activates Deepgram through the normal Admin authority with a synthetic
acquisition policy derived from the stage approvals. The fake broker handles
Deepgram audio bytes before parsing JSON for text providers. These changes
affect tests only; they do not bypass production approval or invoke providers.

This proves stored Deepgram C2 work advances through the real scheduler to C4
with exactly one synthetic transcription call. It does not prove a live C5
report or production cost settlement; those need post-release verification.
