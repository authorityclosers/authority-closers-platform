"""Allowlisted local failure codes; never exception/decoder output text."""

from ac_platform.conversation_intelligence.native_runtime import NativeRuntimeError
from ac_platform.conversation_intelligence.signals import SignalError

_SIGNAL_FAILURES = frozenset(
    {
        "signal_invalid_probe",
        "signal_no_audio_stream",
        "signal_invalid_source_duration",
        "signal_invalid_track_origin",
        "signal_source_missing_or_oversized",
        "signal_unsupported_source_layout",
        "signal_incomplete_pcm_frame",
        "signal_decoded_duration_limit",
        "signal_native_coverage_mismatch",
        "signal_output_exists",
    }
)


def local_failure_code(error: Exception) -> str:
    if type(error) is NativeRuntimeError and error.code in NativeRuntimeError._CODES:
        return error.code
    if type(error) is SignalError and str(error) in _SIGNAL_FAILURES:
        return str(error)
    return "conversation_local_phase_failed"
