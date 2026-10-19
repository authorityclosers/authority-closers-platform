"""Bounded process I/O for the Drive backup candidate; no host actions on import."""

from __future__ import annotations

import os
import selectors
import signal
import subprocess
import time
from contextlib import suppress
from pathlib import Path

CHUNK_BYTES = 64 * 1024
MAX_STDIN_BYTES = 4096
CLEANUP_SECONDS = 2


class ProcessRefusal(RuntimeError):
    """Only fixed codes may cross this boundary; child diagnostics are discarded."""


class Deadline:
    """One monotonic deadline shared by every stage of an operation."""

    def __init__(self, seconds: float = 900):
        if not 0 < seconds <= 900:
            raise ProcessRefusal("invalid_operation_deadline")
        self.expires_at = time.monotonic() + seconds

    def remaining(self) -> float:
        seconds = self.expires_at - time.monotonic()
        if seconds <= 0:
            raise ProcessRefusal("operation_deadline_exceeded")
        return seconds


def _cleanup(process: subprocess.Popen[bytes]) -> None:
    # Each child has a new session. Never signal a shared group or use pkill.
    # Kill the group even after its leader exits: a descendant can retain a pipe.
    with suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGKILL)
    process.wait(timeout=CLEANUP_SECONDS)


def run(
    command: list[str],
    *,
    deadline: Deadline,
    stdout_limit: int,
    input: bytes | None = None,
    destination: Path | None = None,
) -> bytes:
    """Stream stdout with an actual byte cap, to memory or an exclusive file.

    A one-byte read detects output beyond the cap without retaining or writing
    that byte. In file mode no stdout payload is accumulated in Python memory.
    Failed files created by this call are removed; pre-existing files survive.
    All child processes get the same remaining operation time, never 900s each.
    """
    if stdout_limit < 0 or (input is not None and len(input) > MAX_STDIN_BYTES):
        raise ProcessRefusal("invalid_process_io_limit")
    deadline.remaining()
    environment = {
        key: os.environ[key] for key in ("PATH", "HOME", "LANG", "LC_ALL") if key in os.environ
    }
    process = None
    output = None
    created = False
    succeeded = False
    selector = selectors.DefaultSelector()
    captured = bytearray()
    written = 0
    pending = memoryview(input or b"")
    try:
        if destination is not None:
            fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            created = True
            output = os.fdopen(fd, "wb", buffering=0)
        process = subprocess.Popen(  # noqa: S603 - fixed callers; no shell or inherited secrets
            command,
            stdin=subprocess.PIPE if pending else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=environment,
            start_new_session=True,
        )
        assert process.stdout is not None
        os.set_blocking(process.stdout.fileno(), False)
        selector.register(process.stdout, selectors.EVENT_READ, "stdout")
        if process.stdin is not None:
            os.set_blocking(process.stdin.fileno(), False)
            selector.register(process.stdin, selectors.EVENT_WRITE, "stdin")
        while selector.get_map():
            for key, _ in selector.select(timeout=deadline.remaining()):
                deadline.remaining()
                if key.data == "stdin":
                    try:
                        sent = os.write(key.fd, pending)
                        pending = pending[sent:]
                    except BrokenPipeError:
                        pending = memoryview(b"")
                    if not pending:
                        selector.unregister(key.fileobj)
                        key.fileobj.close()
                    continue
                block = os.read(key.fd, min(CHUNK_BYTES, stdout_limit - written + 1))
                if not block:
                    selector.unregister(key.fileobj)
                    key.fileobj.close()
                    continue
                if len(block) > stdout_limit - written:
                    raise ProcessRefusal("child_stdout_limit")
                written += len(block)
                if output is None:
                    captured.extend(block)
                else:
                    pending_output = memoryview(block)
                    while pending_output:
                        count = output.write(pending_output)
                        if not count:
                            raise ProcessRefusal("child_or_local_io_failed")
                        pending_output = pending_output[count:]
        if process.wait(timeout=deadline.remaining()) != 0:
            raise ProcessRefusal("child_failed")
        deadline.remaining()
        if output is not None:
            os.fsync(output.fileno())
        succeeded = True
        return bytes(captured)
    except ProcessRefusal:
        raise
    except subprocess.TimeoutExpired as error:
        raise ProcessRefusal("operation_deadline_exceeded") from error
    except OSError as error:
        raise ProcessRefusal("child_or_local_io_failed") from error
    finally:
        cleanup_error = None
        try:
            if process is not None:
                _cleanup(process)
        except (OSError, subprocess.SubprocessError) as error:
            succeeded = False
            cleanup_error = error
        finally:
            selector.close()
            if process is not None:
                for stream in (process.stdin, process.stdout):
                    if stream is not None:
                        stream.close()
            if output is not None:
                output.close()
            if created and not succeeded:
                assert destination is not None
                destination.unlink(missing_ok=True)
        if cleanup_error is not None:
            raise ProcessRefusal("owned_process_cleanup_failed") from cleanup_error
