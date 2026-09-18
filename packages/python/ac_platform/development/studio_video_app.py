"""Explicit Uvicorn factory for the isolated local Studio video sandbox.

The ordinary application stays inert.  This module composes the existing
local media graph with real file storage, ClamAV and FFmpeg only after the
disposable database target, an exact opt-in and a current managed scanner
proof all validate.  Startup additionally exercises the live daemon before
any route becomes reachable.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
import socket
import stat
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager, closing, suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, cast

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response

import ac_platform.http.app as application_module
from ac_platform.db.session import session_factory
from ac_platform.development.seed import require_local_target
from ac_platform.media.clamav_scanner import ClamAVContentScanner, ClamAVScannerConfig
from ac_platform.media.runtime import create_default_media_runtime
from ac_platform.media.signing import MediaSigner
from ac_platform.media.storage import InMemoryPrivateObjectStorage
from ac_platform.media.studio_video_completion import StudioCompletionSessionFactory
from ac_platform.media.studio_video_delivery import compose_local_studio_video_delivery
from ac_platform.media.studio_video_limits import (
    STUDIO_VIDEO_MAX_SCAN_BYTES,
    STUDIO_VIDEO_MAX_SOURCE_BYTES,
    STUDIO_VIDEO_MAX_STORE_BYTES,
    STUDIO_VIDEO_SCAN_TIMEOUT_SECONDS,
)
from ac_platform.media.studio_video_runner import (
    StudioVideoRunner,
    StudioVideoRunnerSummary,
    StudioVideoRunOnce,
)
from ac_platform.media.studio_video_runtime import compose_local_studio_video_runtime
from ac_platform.media.studio_video_worker import StudioVideoWorkerResult

_MAX_PROOF_BYTES = 16 * 1024
_MAX_PROOF_LIFETIME = timedelta(hours=24)
_MAX_DAILY_DEFINITION_AGE = timedelta(hours=48)
_MONITOR_INTERVAL = timedelta(seconds=60)
_SHA256 = re.compile(r"[0-9a-f]{64}")
_IMAGE_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_CLAMD_VERSION = re.compile(r"[0-9]+(?:\.[0-9]+){1,3}")
_LIVE_VERSION = re.compile(
    rb"ClamAV (?P<clamd>[0-9]+(?:\.[0-9]+){1,3})/(?P<daily>[0-9]+)/[^\x00\r\n]+\x00"
)
_UUID = r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}"
_STUDIO_PREFIX = rf"/v1/admin/studio/programs/{_UUID}"
_CAPABILITY = re.compile(rf"^{_STUDIO_PREFIX}/video-upload-capability$")
_CREATE_UPLOAD = re.compile(rf"^{_STUDIO_PREFIX}/video-uploads$")
_MUTATE_UPLOAD = re.compile(rf"^{_STUDIO_PREFIX}/video-uploads/{_UUID}/(?:bytes|complete)$")

_REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
_LOCAL_PLATFORM_ROOT = _REPOSITORY_ROOT / ".tmp" / "local-platform"
_PROOF_PATH = _LOCAL_PLATFORM_ROOT / "studio-video-scanner-readiness.json"
_VIDEO_ROOT = _LOCAL_PLATFORM_ROOT / "video-objects"


class ScannerDefinitionEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    version: int = Field(gt=0)
    updated_at: AwareDatetime
    sha256: str

    @model_validator(mode="after")
    def validate_hash(self) -> ScannerDefinitionEvidence:
        if _SHA256.fullmatch(self.sha256) is None:
            raise ValueError("scanner definition hash must be lowercase SHA-256")
        return self


class ScannerDefinitionsEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    daily: ScannerDefinitionEvidence
    main: ScannerDefinitionEvidence
    bytecode: ScannerDefinitionEvidence


class LocalStudioVideoScannerReadiness(BaseModel):
    """Immutable managed-policy evidence; never a clean-verdict bypass."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal["ac.local-studio-video-scanner-readiness.v1"]
    environment: Literal["local"]
    host: Literal["127.0.0.1"]
    port: Literal[13310]
    max_source_bytes: Literal[2000000000]
    stream_max_length: int = Field(ge=STUDIO_VIDEO_MAX_SOURCE_BYTES, le=2**31 - 1)
    max_file_size: int = Field(ge=STUDIO_VIDEO_MAX_SOURCE_BYTES, le=2**31 - 1)
    max_scan_size: int = Field(ge=STUDIO_VIDEO_MAX_SCAN_BYTES, le=8 * 1024**3)
    alert_exceeds_max: Literal[True]
    verified_at: AwareDatetime
    expires_at: AwareDatetime
    clamd_version: str
    scanner_image_digest: str
    managed_config_sha256: str
    evidence_sha256: str
    definitions: ScannerDefinitionsEvidence

    @model_validator(mode="after")
    def validate_envelope(self) -> LocalStudioVideoScannerReadiness:
        if (
            _CLAMD_VERSION.fullmatch(self.clamd_version) is None
            or _IMAGE_DIGEST.fullmatch(self.scanner_image_digest) is None
            or _SHA256.fullmatch(self.managed_config_sha256) is None
            or _SHA256.fullmatch(self.evidence_sha256) is None
            or self.expires_at <= self.verified_at
            or self.expires_at - self.verified_at > _MAX_PROOF_LIFETIME
            or any(
                item.updated_at > self.verified_at
                for item in (
                    self.definitions.daily,
                    self.definitions.main,
                    self.definitions.bytecode,
                )
            )
        ):
            raise ValueError("scanner readiness evidence envelope is invalid")
        return self

    def require_current(self, *, now: datetime | None = None) -> None:
        selected = now or datetime.now(UTC)
        if selected.tzinfo is None or selected.utcoffset() is None:
            raise ValueError("scanner readiness time must be timezone-aware")
        current = selected.astimezone(UTC)
        verified = self.verified_at.astimezone(UTC)
        if (
            verified > current
            or current >= self.expires_at.astimezone(UTC)
            or current - self.definitions.daily.updated_at.astimezone(UTC)
            > _MAX_DAILY_DEFINITION_AGE
        ):
            raise RuntimeError("Studio video scanner readiness proof is not current")


class _Readiness:
    def __init__(self, proof: LocalStudioVideoScannerReadiness) -> None:
        self.proof = proof
        self.scanner_ready = False
        self.runner_failed = False
        self.runner_summary: StudioVideoRunnerSummary | None = None

    def available(self) -> bool:
        try:
            self.proof.require_current()
        except (RuntimeError, ValueError):
            return False
        return self.scanner_ready and not self.runner_failed


class _ReadyWorker:
    """Prevent stale scanner policy from admitting another queued job."""

    def __init__(self, readiness: _Readiness, worker: object) -> None:
        if not callable(getattr(worker, "run_once", None)):
            raise TypeError("Studio video worker is unavailable")
        self.readiness = readiness
        self.worker = cast(StudioVideoRunOnce, worker)

    async def run_once(self) -> StudioVideoWorkerResult:
        if not self.readiness.available():
            return StudioVideoWorkerResult()
        result = await self.worker.run_once()
        if type(result) is not StudioVideoWorkerResult:
            raise TypeError("Studio video worker returned an invalid result")
        return result


def _load_proof(path: Path | None = None) -> LocalStudioVideoScannerReadiness:
    selected = _PROOF_PATH if path is None else path
    try:
        for component in (*reversed(selected.parents), selected):
            info = component.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & getattr(
                stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400
            ):
                raise ValueError
            if component != selected and not stat.S_ISDIR(info.st_mode):
                raise ValueError
        before = selected.lstat()
        if (
            selected.is_symlink()
            or not stat.S_ISREG(before.st_mode)
            or before.st_size > _MAX_PROOF_BYTES
        ):
            raise ValueError
        with selected.open("rb") as stream:
            raw = stream.read(_MAX_PROOF_BYTES + 1)
            after = os.fstat(stream.fileno())
        if (
            not raw
            or len(raw) > _MAX_PROOF_BYTES
            or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        ):
            raise ValueError
        proof = LocalStudioVideoScannerReadiness.model_validate_json(raw, strict=True)
        proof.require_current()
        return proof
    except Exception:
        raise RuntimeError("Managed Studio video scanner readiness proof is unavailable") from None


def _clamd_command(config: ClamAVScannerConfig, command: bytes) -> bytes:
    if config.host != "127.0.0.1" or config.port != 13310:
        raise RuntimeError("Studio scanner endpoint changed")
    with closing(
        socket.create_connection(
            (config.host, config.port),
            timeout=config.connect_timeout_seconds,
        )
    ) as connection:
        connection.settimeout(config.io_timeout_seconds)
        connection.sendall(command)
        response = bytearray()
        while True:
            part = connection.recv(min(1024, config.max_response_bytes + 1 - len(response)))
            if not part:
                break
            response.extend(part)
            if len(response) > config.max_response_bytes:
                raise RuntimeError("Studio scanner response was invalid")
    return bytes(response)


def _verify_scanner(
    config: ClamAVScannerConfig,
    proof: LocalStudioVideoScannerReadiness,
) -> None:
    """Check current evidence plus this process's exact live clamd tunnel."""

    try:
        proof.require_current()
        if _clamd_command(config, b"zPING\x00") != b"PONG\x00":
            raise RuntimeError
        version = _LIVE_VERSION.fullmatch(_clamd_command(config, b"zVERSION\x00"))
        if (
            version is None
            or version["clamd"].decode("ascii") != proof.clamd_version
            or int(version["daily"]) != proof.definitions.daily.version
        ):
            raise RuntimeError

        signer = MediaSigner(b"local-studio-scanner-readiness-only-32-bytes")
        storage = InMemoryPrivateObjectStorage(signer)
        scanner = ClamAVContentScanner(config)
        clean = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 16
        clean_key = "scanner-readiness/clean.mp4"
        clean_digest = hashlib.sha256(clean).hexdigest()
        storage.put(object_key=clean_key, body=clean, content_type="video/mp4")
        clean_result = scanner.scan(
            storage=storage,
            object_key=clean_key,
            declared_content_type="video/mp4",
            content_length=len(clean),
            checksum_sha256=clean_digest,
        )
        if not clean_result.clean or clean_result.verified_checksum_sha256 != clean_digest:
            raise RuntimeError

        eicar = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
        malware_key = "scanner-readiness/detection.txt"
        storage.put(object_key=malware_key, body=eicar, content_type="text/plain")
        malware = scanner.scan(
            storage=storage,
            object_key=malware_key,
            declared_content_type="text/plain",
            content_length=len(eicar),
            checksum_sha256=hashlib.sha256(eicar).hexdigest(),
        )
        if malware.clean or malware.reason_code != "MALWARE_DETECTED":
            raise RuntimeError
    except Exception:
        raise RuntimeError("Studio video scanner live verification failed") from None


async def _run_check(
    executor: ThreadPoolExecutor,
    config: ClamAVScannerConfig,
    proof: LocalStudioVideoScannerReadiness,
) -> None:
    future = asyncio.get_running_loop().run_in_executor(executor, _verify_scanner, config, proof)
    try:
        await asyncio.shield(future)
    except asyncio.CancelledError:
        while not future.done():
            try:
                await asyncio.shield(future)
            except asyncio.CancelledError:
                continue
            except BaseException:
                break
        if future.done() and not future.cancelled():
            with suppress(BaseException):
                future.result()
        raise


async def _monitor_scanner(
    stop: asyncio.Event,
    readiness: _Readiness,
    executor: ThreadPoolExecutor,
    config: ClamAVScannerConfig,
) -> None:
    while True:
        if stop.is_set():
            return
        try:
            await asyncio.wait_for(
                stop.wait(),
                timeout=_MONITOR_INTERVAL.total_seconds(),
            )
            return
        except TimeoutError:
            pass
        readiness.scanner_ready = False
        try:
            proof = _load_proof()
            await _run_check(executor, config, proof)
        except Exception:
            readiness.scanner_ready = False
        else:
            readiness.proof = proof
            readiness.scanner_ready = True


async def _drain_all(tasks: tuple[asyncio.Task[Any], ...]) -> None:
    """Drain every owned task even under repeated native cancellation."""

    cancelled = False
    failure: BaseException | None = None
    for task in tasks:
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                cancelled = True
            except BaseException as error:
                failure = failure or error
                break
        if task.done() and not task.cancelled():
            try:
                task.result()
            except BaseException as error:
                failure = failure or error
    if cancelled:
        raise asyncio.CancelledError
    if failure is not None:
        raise failure


def _install_readiness_gate(application: FastAPI, readiness: _Readiness) -> None:
    @application.middleware("http")
    async def studio_video_readiness(
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        available = readiness.available()
        path, method = request.url.path, request.method
        if method == "GET" and _CAPABILITY.fullmatch(path) and not available:
            authorized = await call_next(request)
            if authorized.status_code != 200:
                return authorized
            return JSONResponse(
                {
                    "available": False,
                    "max_source_bytes": None,
                    "accepted_content_types": ["video/mp4", "video/webm"],
                    "reason": "not_configured",
                },
                headers={"Cache-Control": "no-store"},
            )
        upload_mutation = (method == "POST" and _CREATE_UPLOAD.fullmatch(path)) or (
            method in {"PUT", "POST"} and _MUTATE_UPLOAD.fullmatch(path)
        )
        if (path == "/health/ready" or upload_mutation) and not available:
            return JSONResponse(
                {
                    "type": "about:blank",
                    "title": "Service is not ready",
                    "status": 503,
                    "detail": "A critical dependency is unavailable.",
                    "code": "not_ready",
                },
                status_code=503,
                headers={"Cache-Control": "no-store"},
            )
        return await call_next(request)


def _install_lifecycle(
    application: FastAPI,
    readiness: _Readiness,
    runner: StudioVideoRunner,
    config: ClamAVScannerConfig,
) -> None:
    original = application.router.lifespan_context

    @asynccontextmanager
    async def managed(app: FastAPI) -> AsyncIterator[None]:
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="studio-scanner-readiness")
        stop = asyncio.Event()
        monitor: asyncio.Task[None] | None = None
        worker: asyncio.Task[StudioVideoRunnerSummary] | None = None
        try:
            await _run_check(executor, config, readiness.proof)
            readiness.scanner_ready = True
            async with original(app):
                monitor = asyncio.create_task(
                    _monitor_scanner(stop, readiness, executor, config),
                    name="studio-video-scanner-monitor",
                )
                worker = asyncio.create_task(
                    runner.run(stop),
                    name="studio-video-runner",
                )

                def finished(task: asyncio.Task[StudioVideoRunnerSummary]) -> None:
                    failed = task.cancelled()
                    if not failed:
                        failed = task.exception() is not None or not stop.is_set()
                    readiness.runner_failed = failed

                worker.add_done_callback(finished)
                try:
                    yield
                finally:
                    stop.set()
                    owned = tuple(task for task in (monitor, worker) if task is not None)
                    try:
                        await _drain_all(owned)
                    finally:
                        if worker is not None and worker.done() and not worker.cancelled():
                            with suppress(BaseException):
                                readiness.runner_summary = worker.result()
                        if (
                            readiness.runner_failed
                            and worker is not None
                            and not worker.cancelled()
                            and worker.exception() is None
                        ):
                            raise RuntimeError("Studio video runner terminated unexpectedly")
        finally:
            readiness.scanner_ready = False
            executor.shutdown(wait=True)

    application.router.lifespan_context = managed


def create_app() -> FastAPI:
    """Create the explicitly enabled isolated local Studio video application."""

    if os.environ.get("AC_LOCAL_STUDIO_VIDEO_ENABLED") != "true":
        raise RuntimeError("Local Studio video application requires its exact opt-in")
    settings = application_module.settings
    require_local_target(settings, acknowledged=True)
    proof = _load_proof()
    config = ClamAVScannerConfig(
        host=proof.host,
        port=proof.port,
        max_content_bytes=proof.max_source_bytes,
        total_timeout_seconds=STUDIO_VIDEO_SCAN_TIMEOUT_SECONDS,
    )
    runtime = create_default_media_runtime(settings)
    sessions = cast(
        StudioCompletionSessionFactory,
        session_factory,
    )
    runtime = compose_local_studio_video_runtime(
        settings,
        runtime,
        sessions=sessions,
        root=_VIDEO_ROOT,
        max_store_bytes=STUDIO_VIDEO_MAX_STORE_BYTES,
        scanner_config=config,
    )
    runtime = compose_local_studio_video_delivery(settings, runtime)
    application = application_module.create_app(media_runtime=runtime)
    studio = runtime.studio_video_runtime
    if studio is None:
        raise RuntimeError("Local Studio video runtime was not composed")
    readiness = _Readiness(proof)
    application.state.local_studio_video_readiness = readiness
    _install_readiness_gate(application, readiness)
    gated_worker = _ReadyWorker(readiness, studio.worker)
    _install_lifecycle(application, readiness, StudioVideoRunner(gated_worker), config)
    return application


__all__ = [
    "LocalStudioVideoScannerReadiness",
    "ScannerDefinitionEvidence",
    "ScannerDefinitionsEvidence",
    "create_app",
]
