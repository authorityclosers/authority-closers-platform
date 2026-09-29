"""Integrity checks for the fictional Piper sales-call fixture."""

import wave
from hashlib import sha256
from importlib import resources

FIXTURE_PACKAGE = "ac_platform.conversation_intelligence"
FIXTURE_PATH = "canary_fixture/sales_call_v1.wav"
FIXTURE_SHA256 = "454a0353808b53e6535d949781006b49b036f43b8d225db1ec88d46c7996939f"
MAX_FIXTURE_BYTES = 2_000_000


def test_canary_fixture_has_expected_audio_format_size_duration_and_digest() -> None:
    fixture = resources.files(FIXTURE_PACKAGE).joinpath(*FIXTURE_PATH.split("/"))
    payload = fixture.read_bytes()

    assert len(payload) <= MAX_FIXTURE_BYTES
    assert sha256(payload).hexdigest() == FIXTURE_SHA256

    with (
        resources.as_file(fixture) as fixture_path,
        wave.open(str(fixture_path), "rb") as audio,
    ):
        assert audio.getcomptype() == "NONE"
        assert audio.getnchannels() == 1
        assert audio.getsampwidth() == 2
        assert audio.getframerate() == 16_000
        duration = audio.getnframes() / audio.getframerate()

    assert 30 <= duration <= 60
