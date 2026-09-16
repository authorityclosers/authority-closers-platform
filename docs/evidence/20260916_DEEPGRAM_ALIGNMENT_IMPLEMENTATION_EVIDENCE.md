# Deepgram C2 alignment implementation evidence

Candidate commit: `1635260f83fea124786e6103bb8e4db77e4d3378`.

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
- PostgreSQL scheduler regression: **collected but not executed** because this
  environment has neither `AC_CONVERSATION_POSTGRES_TEST_URL` nor
  `AC_TEST_DATABASE_URL`; CI must run it with the disposable PostgreSQL URL.
