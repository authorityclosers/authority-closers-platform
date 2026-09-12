"""A small, private subprocess boundary for provider inference.

The application process owns authorization, reservations and source storage.  It
passes this module an already admitted, in-flight reservation and the exact
immutable request bytes.  The child process is the only process allowed to see
the one provider credential injected by an approved launcher.  This transport
does not authorize a reservation, settle spend, retry a request, or make a
quality claim.

The wire format is length-prefixed JSON metadata followed by an exact binary
payload.  Provider response data is deliberately absent from the metadata: the
parent hashes and deserializes the returned raw JSON itself.
"""

from __future__ import annotations

import asyncio
import ctypes
import hashlib
import json
import os
import re
import struct
import sys
from collections.abc import Awaitable, Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, cast

from ac_platform.conversation_intelligence.checkpoints import canonical
from ac_platform.conversation_intelligence.entitlements import Reservation
from ac_platform.conversation_intelligence.providers import (
    MAX_AUDIO_BYTES,
    MAX_JSON_BYTES,
    BoundedProviders,
    ProviderError,
    ProviderResult,
)

BROKER_SCHEMA = "ac.sales_xray.inference_broker/1"
BROKER_MODULE = "ac_platform.conversation_intelligence.inference_broker_cli"
MAX_HEADER_BYTES = 64 * 1024
MAX_TIMEOUT_SECONDS = 180.0
MAX_FRAME_BYTES = 4 + MAX_HEADER_BYTES + MAX_AUDIO_BYTES
MAX_OUTPUT_FRAME_BYTES = 4 + MAX_HEADER_BYTES + MAX_JSON_BYTES
_FRAME_LENGTH = struct.Struct(">I")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_.:/-]{0,127}$")
_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_:-]{0,127}$")
_REFERENCE = re.compile(r"^[A-Za-z0-9_./:-]{1,256}$")
_SAFE_ERROR = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_PROVIDER_HTTP_ERROR = re.compile(r"^provider_http_[1-5][0-9]{2}$")
_STABLE_ERROR_CODES = frozenset(
    {
        "broker_child_failed",
        "broker_failed",
        "broker_frame_invalid",
        "broker_input_json_invalid",
        "broker_input_json_not_canonical",
        "broker_input_too_large",
        "broker_input_sha256_mismatch",
        "broker_launcher_provider_mismatch",
        "broker_operation_not_supported",
        "broker_payload_must_be_bytes",
        "broker_process_failed",
        "broker_process_tree_unsupported",
        "broker_process_unavailable",
        "broker_provider_result_binding_mismatch",
        "broker_request_id_invalid",
        "broker_request_invalid",
        "broker_request_route_mismatch",
        "broker_reservation_invalid",
        "broker_reservation_not_in_flight",
        "broker_response_invalid",
        "broker_response_json_invalid",
        "broker_response_route_mismatch",
        "broker_response_sha256_mismatch",
        "broker_response_too_large",
        "broker_timeout",
        "broker_usage_invalid",
        "provider_audio_or_model_invalid",
        "provider_dispatch_failed",
        "provider_dispatch_not_authorized",
        "provider_execution_deadline",
        "provider_model_not_supported",
        "provider_output_budget_required",
        "provider_payload_invalid",
        "provider_prompt_too_large",
        "provider_response_invalid",
        "provider_response_too_large",
        "provider_source_binding_mismatch",
        "provider_transport_or_response_failed",
    }
)

# These are the only provider variables that the child is permitted to read.
# The parent never copies any of them into its own command or request frame.
_CREDENTIAL_ENV = {
    "elevenlabs": "ELEVENLABS_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "groq": "GROQ_API_KEY",
}
_PROVIDER_ENV_NAMES = frozenset(_CREDENTIAL_ENV.values())
_RUNTIME_ENV_NAMES = frozenset(
    {
        "PYTHONUTF8",
        "PYTHONPATH",
        "PATH",
        "SystemRoot",
        "WINDIR",
        "TEMP",
        "TMP",
        "TMPDIR",
        "HOME",
        "USERPROFILE",
        "LOCALAPPDATA",
        "APPDATA",
    }
)


class InferenceBrokerError(ValueError):
    """Stable local error code; no source, response, path or credential text."""

    def __init__(self, code: str) -> None:
        lowered = code.lower() if isinstance(code, str) else ""
        if not _is_stable_error_code(code) or any(
            marker in lowered for marker in ("secret", "password", "bearer", "api_key")
        ):
            code = "broker_failed"
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class BrokerLimits:
    """Hard limits applied by the parent transport and never relaxed by a job."""

    timeout_seconds: float = 180.0
    max_input_bytes: int = MAX_AUDIO_BYTES
    max_raw_response_bytes: int = MAX_JSON_BYTES

    def __post_init__(self) -> None:
        if (
            type(self.timeout_seconds) not in {int, float}
            or not 0 < self.timeout_seconds <= MAX_TIMEOUT_SECONDS
            or type(self.max_input_bytes) is not int
            or not 0 < self.max_input_bytes <= MAX_AUDIO_BYTES
            or type(self.max_raw_response_bytes) is not int
            or not 0 < self.max_raw_response_bytes <= MAX_JSON_BYTES
        ):
            raise ValueError("invalid inference broker limits")


def _reference(value: object, field: str) -> str:
    if not isinstance(value, str) or _REFERENCE.fullmatch(value) is None:
        raise ValueError(f"invalid {field}")
    lowered = value.lower()
    if any(
        marker in lowered
        for marker in (
            "?",
            "#",
            "@",
            "token=",
            "secret=",
            "password=",
            "api_key=",
            "sk-",
            "sk_",
            "aq.",
        )
    ):
        raise ValueError(f"invalid {field}")
    if any(part == ".." for part in value.split("/")):
        raise ValueError(f"invalid {field}")
    return value


def _is_stable_error_code(code: object) -> bool:
    return isinstance(code, str) and (
        code in _STABLE_ERROR_CODES or _PROVIDER_HTTP_ERROR.fullmatch(code) is not None
    )


@dataclass(frozen=True, slots=True)
class InfisicalLauncher:
    """Approved, non-secret Infisical references for one fixed child command."""

    executable: str | Path
    provider_id: str
    project_ref: str
    environment_ref: str
    secret_path_ref: str

    def __post_init__(self) -> None:
        executable = str(self.executable)
        # A bare executable name is accepted only for the fixed Infisical tool.
        # Any configured path must be absolute; no shell string is ever accepted.
        if not executable or (
            Path(executable).name.lower() not in {"infisical", "infisical.exe"}
            or (Path(executable).name != executable and not Path(executable).is_absolute())
        ):
            raise ValueError("invalid infisical executable")
        if _IDENTIFIER.fullmatch(self.provider_id) is None:
            raise ValueError("invalid provider id")
        _reference(self.project_ref, "project reference")
        _reference(self.environment_ref, "environment reference")
        _reference(self.secret_path_ref, "secret path reference")
        if self.secret_path_ref.rstrip("/").split("/")[-1] != self.provider_id:
            raise ValueError("provider-specific secret path required")

    def argv(self, python_executable: str) -> tuple[str, ...]:
        """Build the only permitted wrapper argv; values are references, not secrets."""

        return (
            str(self.executable),
            "run",
            "--include-imports=false",
            "--expand=false",
            "--silent",
            "--telemetry=false",
            "--log-level=error",
            "--projectId",
            self.project_ref,
            "--env",
            self.environment_ref,
            "--path",
            self.secret_path_ref,
            "--",
            python_executable,
            "-m",
            BROKER_MODULE,
            "--child",
        )


class ProcessRunner(Protocol):
    async def run(
        self,
        argv: Sequence[str],
        request: bytes,
        *,
        environment: Mapping[str, str],
        timeout_seconds: float,
        max_output_bytes: int,
    ) -> bytes: ...


class _WindowsIoCounters(ctypes.Structure):
    _fields_ = [
        ("read_operation_count", ctypes.c_ulonglong),
        ("write_operation_count", ctypes.c_ulonglong),
        ("other_operation_count", ctypes.c_ulonglong),
        ("read_transfer_count", ctypes.c_ulonglong),
        ("write_transfer_count", ctypes.c_ulonglong),
        ("other_transfer_count", ctypes.c_ulonglong),
    ]


class _WindowsBasicLimitInformation(ctypes.Structure):
    _fields_ = [
        ("per_process_user_time", ctypes.c_longlong),
        ("per_job_user_time", ctypes.c_longlong),
        ("limit_flags", ctypes.c_ulong),
        ("minimum_working_set_size", ctypes.c_size_t),
        ("maximum_working_set_size", ctypes.c_size_t),
        ("active_process_limit", ctypes.c_ulong),
        ("affinity", ctypes.c_size_t),
        ("priority_class", ctypes.c_ulong),
        ("scheduling_class", ctypes.c_ulong),
    ]


class _WindowsExtendedLimitInformation(ctypes.Structure):
    _fields_ = [
        ("basic_limit_information", _WindowsBasicLimitInformation),
        ("io_info", _WindowsIoCounters),
        ("process_memory_limit", ctypes.c_size_t),
        ("job_memory_limit", ctypes.c_size_t),
        ("peak_process_memory_used", ctypes.c_size_t),
        ("peak_job_memory_used", ctypes.c_size_t),
    ]


class _WindowsJob:
    """Small kill-on-close Job Object wrapper, loaded only on Windows."""

    _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
    _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
    _PROCESS_TERMINATE = 0x0001
    _PROCESS_SET_QUOTA = 0x0100
    _PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    _PROCESS_SUSPEND_RESUME = 0x0800

    def __init__(self, handle: Any) -> None:
        self.handle = handle

    @staticmethod
    def _kernel32() -> Any:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
        kernel32.CreateJobObjectW.restype = ctypes.c_void_p
        kernel32.SetInformationJobObject.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_uint32,
        ]
        kernel32.SetInformationJobObject.restype = ctypes.c_int
        kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        kernel32.AssignProcessToJobObject.restype = ctypes.c_int
        kernel32.TerminateJobObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        kernel32.TerminateJobObject.restype = ctypes.c_int
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.restype = ctypes.c_int
        return kernel32

    @classmethod
    def attach(cls, pid: int) -> _WindowsJob:
        kernel32 = cls._kernel32()
        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            raise InferenceBrokerError("broker_process_tree_unsupported")
        try:
            information = _WindowsExtendedLimitInformation()
            information.basic_limit_information.limit_flags = (
                cls._JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            )
            if not kernel32.SetInformationJobObject(
                job,
                cls._JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
                ctypes.byref(information),
                ctypes.sizeof(information),
            ):
                raise InferenceBrokerError("broker_process_tree_unsupported")
            process = kernel32.OpenProcess(
                cls._PROCESS_TERMINATE
                | cls._PROCESS_SET_QUOTA
                | cls._PROCESS_QUERY_LIMITED_INFORMATION
                | cls._PROCESS_SUSPEND_RESUME,
                False,
                pid,
            )
            if not process:
                raise InferenceBrokerError("broker_process_tree_unsupported")
            try:
                if not kernel32.AssignProcessToJobObject(job, process):
                    raise InferenceBrokerError("broker_process_tree_unsupported")
            finally:
                kernel32.CloseHandle(process)
            return cls(job)
        except Exception:
            kernel32.CloseHandle(job)
            raise

    def terminate(self) -> None:
        kernel32 = self._kernel32()
        kernel32.TerminateJobObject(self.handle, 1)

    def kill(self) -> None:
        self.terminate()

    @classmethod
    def resume_process(cls, pid: int) -> None:
        try:
            kernel32 = cls._kernel32()
            process = kernel32.OpenProcess(cls._PROCESS_SUSPEND_RESUME, False, pid)
        except OSError:
            raise InferenceBrokerError("broker_process_tree_unsupported") from None
        if not process:
            raise InferenceBrokerError("broker_process_tree_unsupported")
        try:
            try:
                ntdll = ctypes.WinDLL("ntdll")
                ntdll.NtResumeProcess.argtypes = [ctypes.c_void_p]
                ntdll.NtResumeProcess.restype = ctypes.c_long
            except OSError:
                raise InferenceBrokerError("broker_process_tree_unsupported") from None
            if ntdll.NtResumeProcess(process) != 0:
                raise InferenceBrokerError("broker_process_tree_unsupported")
        finally:
            kernel32.CloseHandle(process)

    def close(self) -> None:
        kernel32 = self._kernel32()
        kernel32.CloseHandle(self.handle)


class _ProcessTreeGuard:
    """Own a process group (POSIX) or kill-on-close Job Object (Windows)."""

    def __init__(self, pid: int) -> None:
        self.pid = pid
        self._windows_job: _WindowsJob | None = None

    def attach(self) -> None:
        if os.name == "nt" and self._windows_job is None:
            try:
                self._windows_job = _WindowsJob.attach(self.pid)
            except InferenceBrokerError:
                raise
            except Exception:
                raise InferenceBrokerError("broker_process_tree_unsupported") from None

    def terminate(self, process: asyncio.subprocess.Process) -> None:
        if self._windows_job is not None:
            self._windows_job.terminate()
            return
        if os.name == "posix":
            killpg = cast(Callable[[int, int], None], getattr(os, "killpg", None))
            try:
                if killpg is None:
                    raise OSError
                killpg(self.pid, 15)
                return
            except (OSError, ProcessLookupError, PermissionError):
                pass
        with suppress(ProcessLookupError):
            process.terminate()

    def kill(self, process: asyncio.subprocess.Process) -> None:
        if self._windows_job is not None:
            self._windows_job.kill()
            return
        if os.name == "posix":
            killpg = cast(Callable[[int, int], None], getattr(os, "killpg", None))
            try:
                if killpg is None:
                    raise OSError
                killpg(self.pid, 9)
                return
            except (OSError, ProcessLookupError, PermissionError):
                pass
        with suppress(ProcessLookupError):
            process.kill()

    def close(self) -> None:
        if self._windows_job is not None:
            self._windows_job.close()
            self._windows_job = None

    def resume(self) -> None:
        if self._windows_job is not None:
            _WindowsJob.resume_process(self.pid)


def _subprocess_kwargs() -> dict[str, Any]:
    if os.name == "nt":
        # CREATE_SUSPENDED lets the Job Object own the entire future process
        # tree before either the wrapper or its child receives request bytes.
        return {
            "creationflags": 0x00000200 | 0x00000004 | 0x08000000
        }  # NEW_PROCESS_GROUP|SUSPENDED|NO_WINDOW
    return {"start_new_session": True}


async def _read_bounded(stream: asyncio.StreamReader, maximum: int) -> bytes:
    captured = bytearray()
    while True:
        block = await stream.read(min(65_536, maximum + 1 - len(captured)))
        if not block:
            return bytes(captured)
        captured.extend(block)
        if len(captured) > maximum:
            raise InferenceBrokerError("broker_response_too_large")


async def _join_process(
    process: asyncio.subprocess.Process,
    reader: asyncio.Task[bytes],
    guard: _ProcessTreeGuard,
) -> None:
    """Terminate/kill and join both process and reader, including cancellation paths."""

    try:
        if process.returncode is None:
            guard.terminate(process)
            try:
                await asyncio.wait_for(process.wait(), timeout=0.25)
            except (TimeoutError, ProcessLookupError):
                guard.kill(process)
        else:
            # A wrapper can exit while a descendant still holds the pipe.
            # Killing the group/job also handles this completed-wrapper case.
            guard.kill(process)
        with suppress(ProcessLookupError):
            await process.wait()
        with suppress(asyncio.CancelledError, InferenceBrokerError, OSError):
            await reader
    finally:
        with suppress(BaseException):
            guard.close()


async def _drain_task(task: asyncio.Task[Any]) -> None:
    """Join cleanup despite repeated cancellation of the owning coroutine."""

    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            continue
        except BaseException:
            break
    if task.done() and not task.cancelled():
        with suppress(BaseException):
            task.exception()


async def _cleanup_joined(
    process: asyncio.subprocess.Process,
    reader: asyncio.Task[bytes],
    guard: _ProcessTreeGuard,
) -> None:
    cleanup = asyncio.create_task(_join_process(process, reader, guard))
    await _drain_task(cleanup)


async def _spawn_process(
    argv: Sequence[str], environment: Mapping[str, str]
) -> asyncio.subprocess.Process:
    return await asyncio.create_subprocess_exec(
        *tuple(argv),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        env=dict(environment),
        close_fds=True,
        **_subprocess_kwargs(),
    )


async def _finish_spawn_task(
    task: asyncio.Task[asyncio.subprocess.Process],
) -> asyncio.subprocess.Process | None:
    """Resolve/cancel process creation so cancellation cannot orphan a child."""

    try:
        return await asyncio.wait_for(asyncio.shield(task), timeout=0.5)
    except (TimeoutError, asyncio.CancelledError, OSError, ValueError):
        task.cancel()
        with suppress(asyncio.CancelledError, OSError, ValueError):
            await asyncio.shield(task)
        return None


async def _run_subprocess(
    argv: Sequence[str],
    request: bytes,
    *,
    environment: Mapping[str, str],
    timeout_seconds: float,
    max_output_bytes: int,
) -> bytes:
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    spawn_task = asyncio.create_task(_spawn_process(argv, environment))
    process: asyncio.subprocess.Process | None = None
    guard: _ProcessTreeGuard | None = None
    reader: asyncio.Task[bytes] | None = None
    cleanup_done = False
    try:
        try:
            process = await asyncio.wait_for(
                asyncio.shield(spawn_task),
                timeout=max(0.01, deadline - asyncio.get_running_loop().time()),
            )
        except (OSError, ValueError):
            raise InferenceBrokerError("broker_process_unavailable") from None
        except TimeoutError:
            process = await _finish_spawn_task(spawn_task)
            if process is None:
                raise InferenceBrokerError("broker_process_tree_unsupported") from None
            guard = _ProcessTreeGuard(process.pid)
            assert process.stdout is not None
            reader = asyncio.create_task(_read_bounded(process.stdout, max_output_bytes))
            with suppress(InferenceBrokerError):
                guard.attach()
            if guard._windows_job is None and os.name == "nt":
                await _cleanup_joined(process, reader, guard)
                cleanup_done = True
                raise InferenceBrokerError("broker_process_tree_unsupported") from None
            await _cleanup_joined(process, reader, guard)
            cleanup_done = True
            raise InferenceBrokerError("broker_timeout") from None
        guard = _ProcessTreeGuard(process.pid)
        assert process.stdout is not None
        reader = asyncio.create_task(_read_bounded(process.stdout, max_output_bytes))
        try:
            guard.attach()
        except InferenceBrokerError:
            await _cleanup_joined(process, reader, guard)
            cleanup_done = True
            raise
        try:
            guard.resume()
        except InferenceBrokerError:
            await _cleanup_joined(process, reader, guard)
            cleanup_done = True
            raise
        assert process.stdin is not None
        try:
            remaining = max(0.01, deadline - asyncio.get_running_loop().time())
            await asyncio.wait_for(_write_request(process.stdin, request), timeout=remaining)
            output = await asyncio.wait_for(
                reader,
                timeout=max(0.01, deadline - asyncio.get_running_loop().time()),
            )
        except TimeoutError:
            await _cleanup_joined(process, reader, guard)
            cleanup_done = True
            raise InferenceBrokerError("broker_timeout") from None
        try:
            return_code = await asyncio.wait_for(
                process.wait(), timeout=max(0.01, deadline - asyncio.get_running_loop().time())
            )
        except TimeoutError:
            await _cleanup_joined(process, reader, guard)
            cleanup_done = True
            raise InferenceBrokerError("broker_timeout") from None
        if return_code != 0:
            raise InferenceBrokerError("broker_process_failed")
        return output
    except asyncio.CancelledError:
        process = process or await _finish_spawn_task(spawn_task)
        if process is not None:
            guard = guard or _ProcessTreeGuard(process.pid)
            if reader is None and process.stdout is not None:
                reader = asyncio.create_task(_read_bounded(process.stdout, max_output_bytes))
            with suppress(InferenceBrokerError):
                guard.attach()
            if reader is not None:
                cleanup = asyncio.create_task(_join_process(process, reader, guard))
                await _drain_task(cleanup)
                cleanup_done = True
        raise
    except InferenceBrokerError:
        raise
    except (BrokenPipeError, ConnectionError, OSError):
        raise InferenceBrokerError("broker_process_failed") from None
    finally:
        if not cleanup_done and process is not None and guard is not None and reader is not None:
            await _cleanup_joined(process, reader, guard)


async def _write_request(stream: asyncio.StreamWriter, request: bytes) -> None:
    stream.write(request)
    await stream.drain()
    stream.close()


def _encode_frame(header: Mapping[str, Any], payload: bytes) -> bytes:
    if type(payload) is not bytes:
        raise InferenceBrokerError("broker_payload_must_be_bytes")
    try:
        encoded_header = canonical(dict(header))
    except (TypeError, ValueError):
        raise InferenceBrokerError("broker_frame_invalid") from None
    if not 0 < len(encoded_header) <= MAX_HEADER_BYTES:
        raise InferenceBrokerError("broker_frame_invalid")
    return _FRAME_LENGTH.pack(len(encoded_header)) + encoded_header + payload


def _decode_frame(frame: bytes, *, maximum_payload: int) -> tuple[dict[str, Any], bytes]:
    if type(frame) is not bytes or len(frame) < _FRAME_LENGTH.size:
        raise InferenceBrokerError("broker_frame_invalid")
    header_length = _FRAME_LENGTH.unpack(frame[: _FRAME_LENGTH.size])[0]
    if not 0 < header_length <= MAX_HEADER_BYTES:
        raise InferenceBrokerError("broker_frame_invalid")
    header_end = _FRAME_LENGTH.size + header_length
    if len(frame) < header_end:
        raise InferenceBrokerError("broker_frame_invalid")
    try:
        header = json.loads(frame[_FRAME_LENGTH.size : header_end])
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, TypeError):
        raise InferenceBrokerError("broker_frame_invalid") from None
    if not isinstance(header, dict):
        raise InferenceBrokerError("broker_frame_invalid")
    payload_length = header.get("payload_len")
    if type(payload_length) is not int or not 0 <= payload_length <= maximum_payload:
        raise InferenceBrokerError("broker_frame_invalid")
    payload = frame[header_end:]
    if len(payload) != payload_length:
        raise InferenceBrokerError("broker_frame_invalid")
    return cast(dict[str, Any], header), payload


def _identifier(value: object, field: str, *, allow_none: bool = False) -> str | None:
    if allow_none and value is None:
        return None
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise InferenceBrokerError(f"broker_{field}_invalid")
    return value


def _request_id(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or _REQUEST_ID.fullmatch(value) is None:
        raise InferenceBrokerError("broker_request_id_invalid")
    return value


def _verify_digest(value: object, expected: str, field: str) -> None:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None or value != expected:
        raise InferenceBrokerError(f"broker_{field}_mismatch")


def _request_header(reservation: Reservation, payload: bytes) -> dict[str, Any]:
    quote = reservation.quote
    if reservation.state != "in_flight" or not reservation.attempt_id:
        raise InferenceBrokerError("broker_reservation_not_in_flight")
    if quote.operation not in {"transcribe_scribe_v2", "extract_context_evidence"}:
        raise InferenceBrokerError("broker_operation_not_supported")
    if type(payload) is not bytes or not 0 < len(payload) <= MAX_AUDIO_BYTES:
        raise InferenceBrokerError("broker_input_too_large")
    payload_digest = hashlib.sha256(payload).hexdigest()
    _verify_digest(quote.input_sha256, payload_digest, "input_sha256")
    if quote.operation == "extract_context_evidence":
        try:
            decoded = json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise InferenceBrokerError("broker_input_json_invalid") from None
        if not isinstance(decoded, dict) or canonical(decoded) != payload:
            raise InferenceBrokerError("broker_input_json_not_canonical")
    try:
        snapshot = reservation.as_dict()
    except (TypeError, ValueError):
        raise InferenceBrokerError("broker_reservation_invalid") from None
    return {
        "schema": BROKER_SCHEMA,
        "kind": "request",
        "provider": quote.provider_id,
        "model": quote.provider_model,
        "operation": quote.operation,
        "input_sha256": payload_digest,
        "payload_len": len(payload),
        "reservation": snapshot,
    }


def _safe_usage(value: object) -> dict[str, int]:
    if not isinstance(value, dict) or len(value) > 64:
        raise InferenceBrokerError("broker_usage_invalid")
    result: dict[str, int] = {}
    for key, amount in value.items():
        if not isinstance(key, str) or _IDENTIFIER.fullmatch(key) is None:
            raise InferenceBrokerError("broker_usage_invalid")
        if type(amount) is not int or not 0 <= amount <= 1_000_000_000:
            raise InferenceBrokerError("broker_usage_invalid")
        result[key] = amount
    return result


def _decode_response(
    frame: bytes,
    reservation: Reservation,
    payload: bytes,
    *,
    maximum_payload: int,
) -> ProviderResult:
    header, raw_json = _decode_frame(frame, maximum_payload=maximum_payload)
    expected_success = {
        "schema",
        "kind",
        "status",
        "provider",
        "model",
        "request_id",
        "input_sha256",
        "response_sha256",
        "payload_len",
        "usage",
    }
    if header.get("schema") != BROKER_SCHEMA or header.get("kind") != "response":
        raise InferenceBrokerError("broker_response_invalid")
    status = header.get("status")
    if status == "error":
        if set(header) != {"schema", "kind", "status", "error_code", "payload_len"}:
            raise InferenceBrokerError("broker_response_invalid")
        if header.get("payload_len") != 0:
            raise InferenceBrokerError("broker_response_invalid")
        code = header.get("error_code")
        if not isinstance(code, str) or not _is_stable_error_code(code):
            raise InferenceBrokerError("broker_child_failed")
        # A child may only report stable classes.  Credential-shaped output is
        # always collapsed before it reaches the application error boundary.
        lowered = code.lower()
        if any(marker in lowered for marker in ("secret", "password", "bearer", "api_key")):
            raise InferenceBrokerError("broker_child_failed")
        raise InferenceBrokerError(code)
    if status != "ok" or set(header) != expected_success:
        raise InferenceBrokerError("broker_response_invalid")
    quote = reservation.quote
    if header.get("provider") != quote.provider_id or header.get("model") != quote.provider_model:
        raise InferenceBrokerError("broker_response_route_mismatch")
    payload_digest = hashlib.sha256(payload).hexdigest()
    _verify_digest(header.get("input_sha256"), payload_digest, "input_sha256")
    _verify_digest(header.get("input_sha256"), quote.input_sha256, "input_sha256")
    if type(header.get("payload_len")) is not int or header["payload_len"] != len(raw_json):
        raise InferenceBrokerError("broker_response_invalid")
    response_sha = header.get("response_sha256")
    _verify_digest(response_sha, hashlib.sha256(raw_json).hexdigest(), "response_sha256")
    request_id = _request_id(header.get("request_id"))
    try:
        data = json.loads(raw_json)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise InferenceBrokerError("broker_response_json_invalid") from None
    if not isinstance(data, dict):
        raise InferenceBrokerError("broker_response_json_invalid")
    return ProviderResult(
        provider=quote.provider_id,
        model=quote.provider_model,
        request_id=request_id,
        response_sha256=cast(str, response_sha),
        raw_json=raw_json,
        data=cast(dict[str, Any], data),
        usage=_safe_usage(header.get("usage")),
        input_sha256=cast(str, header["input_sha256"]),
    )


def _safe_child_environment() -> dict[str, str]:
    """Return only runtime plumbing; provider credentials are never inherited."""

    package_root = Path(__file__).resolve().parents[2]
    environment = {
        "PYTHONUTF8": "1",
        "PYTHONPATH": str(package_root),
    }
    for name in (
        "PATH",
        "SystemRoot",
        "WINDIR",
        "TEMP",
        "TMP",
        "TMPDIR",
        "HOME",
        "USERPROFILE",
        "LOCALAPPDATA",
        "APPDATA",
    ):
        value = os.environ.get(name)
        if value:
            environment[name] = value
    for name in _PROVIDER_ENV_NAMES:
        environment.pop(name, None)
    return environment


class ProcessInferenceBroker:
    """Run one admitted provider request in a joined, bounded child process."""

    def __init__(
        self,
        *,
        python_executable: str | Path = sys.executable,
        infisical: InfisicalLauncher | None = None,
        limits: BrokerLimits | None = None,
        runner: ProcessRunner | Callable[..., Awaitable[bytes]] | None = None,
    ) -> None:
        executable = str(python_executable)
        if not executable or not Path(executable).is_absolute():
            raise ValueError("python executable must be an absolute path")
        self._python_executable = executable
        self._infisical = infisical
        self._limits = limits or BrokerLimits()
        self._runner = runner

    def _argv(self, provider_id: str | None = None) -> tuple[str, ...]:
        if self._infisical is not None:
            if provider_id is not None and self._infisical.provider_id != provider_id:
                raise InferenceBrokerError("broker_launcher_provider_mismatch")
            return self._infisical.argv(self._python_executable)
        return (self._python_executable, "-m", BROKER_MODULE, "--child")

    async def execute(self, reservation: Reservation, payload: bytes) -> ProviderResult:
        """Execute one exact request; callers settle/reconcile separately."""

        if not isinstance(reservation, Reservation):
            raise InferenceBrokerError("broker_reservation_invalid")
        if type(payload) is not bytes or not 0 < len(payload) <= self._limits.max_input_bytes:
            raise InferenceBrokerError("broker_input_too_large")
        header = _request_header(reservation, payload)
        provider_id = reservation.quote.provider_id
        request = _encode_frame(header, payload)
        runner = self._runner
        try:
            if runner is None:
                output = await _run_subprocess(
                    self._argv(provider_id),
                    request,
                    environment=_safe_child_environment(),
                    timeout_seconds=self._limits.timeout_seconds,
                    max_output_bytes=min(
                        MAX_OUTPUT_FRAME_BYTES,
                        4 + MAX_HEADER_BYTES + self._limits.max_raw_response_bytes,
                    ),
                )
            elif hasattr(runner, "run"):
                run = cast(Callable[..., Awaitable[bytes]], runner.run)
                output = await run(
                    self._argv(provider_id),
                    request,
                    environment=_safe_child_environment(),
                    timeout_seconds=self._limits.timeout_seconds,
                    max_output_bytes=4 + MAX_HEADER_BYTES + self._limits.max_raw_response_bytes,
                )
            else:
                run = runner
                output = await run(
                    self._argv(provider_id),
                    request,
                    environment=_safe_child_environment(),
                    timeout_seconds=self._limits.timeout_seconds,
                    max_output_bytes=4 + MAX_HEADER_BYTES + self._limits.max_raw_response_bytes,
                )
        except asyncio.CancelledError:
            raise
        except InferenceBrokerError:
            raise
        except Exception:
            raise InferenceBrokerError("broker_process_failed") from None
        return _decode_response(
            output,
            reservation,
            payload,
            maximum_payload=self._limits.max_raw_response_bytes,
        )


def _child_response_error(code: str) -> bytes:
    safe_code = code if _is_stable_error_code(code) else "broker_child_failed"
    if any(marker in safe_code.lower() for marker in ("secret", "password", "bearer", "api_key")):
        safe_code = "broker_child_failed"
    return _encode_frame(
        {
            "schema": BROKER_SCHEMA,
            "kind": "response",
            "status": "error",
            "error_code": safe_code,
            "payload_len": 0,
        },
        b"",
    )


def _child_execute(frame: bytes) -> bytes:
    """Handle one frame inside the fixed child module; private for CLI/tests."""

    try:
        header, payload = _decode_frame(frame, maximum_payload=MAX_AUDIO_BYTES)
        request_fields = {
            "schema",
            "kind",
            "provider",
            "model",
            "operation",
            "input_sha256",
            "payload_len",
            "reservation",
        }
        if (
            set(header) != request_fields
            or header.get("schema") != BROKER_SCHEMA
            or header.get("kind") != "request"
        ):
            raise InferenceBrokerError("broker_request_invalid")
        provider = _identifier(header.get("provider"), "provider")
        model = _identifier(header.get("model"), "model")
        operation = _identifier(header.get("operation"), "operation")
        assert provider is not None and model is not None and operation is not None
        if operation not in {"transcribe_scribe_v2", "extract_context_evidence"}:
            raise InferenceBrokerError("broker_operation_not_supported")
        reservation_value = header.get("reservation")
        reservation = Reservation.from_dict(reservation_value)
        quote = reservation.quote
        if (provider, model, operation) != (
            quote.provider_id,
            quote.provider_model,
            quote.operation,
        ):
            raise InferenceBrokerError("broker_request_route_mismatch")
        digest = hashlib.sha256(payload).hexdigest()
        _verify_digest(header.get("input_sha256"), digest, "input_sha256")
        _verify_digest(quote.input_sha256, digest, "input_sha256")
        if operation == "extract_context_evidence":
            try:
                body = json.loads(payload)
            except (UnicodeDecodeError, json.JSONDecodeError):
                raise InferenceBrokerError("broker_input_json_invalid") from None
            if not isinstance(body, dict) or canonical(body) != payload:
                raise InferenceBrokerError("broker_input_json_not_canonical")
        else:
            body = None
        credential_name = _CREDENTIAL_ENV.get(provider)
        if credential_name is None:
            raise InferenceBrokerError("provider_model_not_supported")
        credential = os.environ.pop(credential_name, "")
        # Never expose a second credential, database setting or launcher token
        # to the adapter, even if an external launcher injects extra names.
        for name in tuple(os.environ):
            if name not in _RUNTIME_ENV_NAMES:
                os.environ.pop(name, None)

        def authorize(current: Reservation) -> None:
            if current != reservation:
                raise ProviderError("broker_reservation_mismatch")

        adapter = BoundedProviders(credentials={provider: credential}, authorize=authorize)
        result = (
            adapter.transcribe(reservation, payload)
            if operation == "transcribe_scribe_v2"
            else adapter.generate(reservation, cast(dict[str, Any], body))
        )
        response_sha = hashlib.sha256(result.raw_json).hexdigest()
        if (
            result.provider != provider
            or result.model != model
            or result.response_sha256 != response_sha
            or result.input_sha256 != digest
        ):
            raise InferenceBrokerError("broker_provider_result_binding_mismatch")
        if len(result.raw_json) > MAX_JSON_BYTES:
            raise InferenceBrokerError("broker_response_too_large")
        return _encode_frame(
            {
                "schema": BROKER_SCHEMA,
                "kind": "response",
                "status": "ok",
                "provider": result.provider,
                "model": result.model,
                "request_id": result.request_id,
                "input_sha256": result.input_sha256,
                "response_sha256": response_sha,
                "payload_len": len(result.raw_json),
                "usage": dict(result.usage),
            },
            result.raw_json,
        )
    except InferenceBrokerError as error:
        return _child_response_error(error.code)
    except (ProviderError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return _child_response_error("provider_dispatch_failed")
    except Exception:
        return _child_response_error("broker_child_failed")


def child_main() -> int:
    """Fixed child entrypoint.  It emits one private response frame only."""

    try:
        frame = sys.stdin.buffer.read(MAX_FRAME_BYTES + 1)
        if len(frame) > MAX_FRAME_BYTES:
            output = _child_response_error("broker_input_too_large")
        else:
            output = _child_execute(frame)
        sys.stdout.buffer.write(output)
        sys.stdout.buffer.flush()
        return 0
    except Exception:
        # The parent sees only a stable frame or process failure; no traceback
        # or child-side exception text is written to the private pipe.
        try:
            sys.stdout.buffer.write(_child_response_error("broker_child_failed"))
            sys.stdout.buffer.flush()
        except Exception:
            return 1
        return 1


__all__ = [
    "BROKER_MODULE",
    "BROKER_SCHEMA",
    "BrokerLimits",
    "InferenceBrokerError",
    "InfisicalLauncher",
    "ProcessInferenceBroker",
    "ProcessRunner",
    "child_main",
]
