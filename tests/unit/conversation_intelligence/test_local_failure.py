"""Provider/native payloads never become operational failure text."""

import pytest

from ac_platform.conversation_intelligence.local_failure import local_failure_code
from ac_platform.conversation_intelligence.native_runtime import NativeRuntimeError
from ac_platform.conversation_intelligence.signals import SignalError


@pytest.mark.parametrize(
    "code",
    ["native_runtime_timeout", "native_runtime_feature_invalid", "native_runtime_output_exists"],
)
def test_known_native_category_is_retained(code: str) -> None:
    assert local_failure_code(NativeRuntimeError(code)) == code


@pytest.mark.parametrize(
    "error", [RuntimeError("private contents"), SignalError("private contents")]
)
def test_arbitrary_exception_text_is_discarded(error: Exception) -> None:
    assert local_failure_code(error) == "conversation_local_phase_failed"


def test_mutated_native_code_cannot_enter_audit() -> None:
    error = NativeRuntimeError("native_runtime_timeout")
    error.code = "private contents"
    assert local_failure_code(error) == "conversation_local_phase_failed"
