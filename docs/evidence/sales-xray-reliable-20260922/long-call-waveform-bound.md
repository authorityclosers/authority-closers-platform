# Long-call waveform bound evidence

The saved synthetic long-call C1 checkpoint is valid native AudioAtlas data but
was rejected by the measurement view's former `expected_rows > 360000` guard.
A SELECT/SHOW-only diagnostic (transaction rolled back) recorded:

- `media_duration_ms`: `3597994`
- `source_channels`: `2`
- decoded rate: `16000`
- `sample_count`: `57567906`
- `rows`: `719600` (`359800` frames per channel)
- `uncompressed_payload_bytes`: `47493600`
- one C1 checkpoint and feature blob present

The persisted artifact is below the existing one-hour native limit and the
shared signal limits (`360000` rows per channel, `720000` total rows). The
measurement view now reuses those limits and explicitly rejects durations over
`3600000` ms. This permits the saved two-channel artifact without relaxing
source, checkpoint, payload, display-series, or authorization validation.

The isolated candidate probe against the saved C1 produced a waveform with
duration `3597994`, `1200` points, first point `0` ms, last point `3597000` ms,
and levels bounded to `[0, 1]`. It ran source validation in an API-container
Python process with SELECT-only guards, with zero provider calls and zero DB
writes; it is a candidate probe, not deployed acceptance.

Evidence receipts are private synthetic fixtures:

- `D:\AuthorityClosers-Private\sales-xray-reliable-20260922\long-call-c1-measurement-bound-receipt.json` — SHA-256 `e03bd73eba0da2121297f5aa929825c66b6f0d2fa6d276e3b9ad3c901154c752`
- `D:\AuthorityClosers-Private\sales-xray-reliable-20260922\long-waveform-candidate-probe.json` — SHA-256 `f7a2c233cdcf654ca4c7ed34c1f940f0276a07c5ea7ba5c48da3a6a2d648ed06`

Validation run on 2026-09-23:

- `tests/unit/conversation_intelligence/test_measurement_view.py`: 8 passed
- `tests/database/test_conversation_measurement_view_postgresql.py`: 1 passed
- Ruff format/check passed for the owned implementation and unit test files.
