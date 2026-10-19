"""The bundled canary recording counts as a test call wherever metrics exclude canaries."""

import hashlib
from importlib import resources

from ac_platform.conversation_intelligence.canary import fixture_sha256s
from ac_platform.conversation_intelligence.canary_cli import FIXTURE_SHA256


def test_fixture_sha256s_include_the_qa_and_canary_recording() -> None:
    wav = (
        resources.files("ac_platform.conversation_intelligence")
        .joinpath("canary_fixture/sales_call_v1.wav")
        .read_bytes()
    )
    assert hashlib.sha256(wav).hexdigest() == FIXTURE_SHA256
    assert FIXTURE_SHA256 in fixture_sha256s()
    assert all(len(sha) == 64 for sha in fixture_sha256s())
